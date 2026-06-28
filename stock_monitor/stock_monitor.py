#!/usr/bin/env python3
"""
Stock-Monitor – prüft Produktseiten auf Online-Bestellbarkeit und meldet
per Telegram, sobald ein Artikel wieder bestellbar wird.

Eigenständiges Zusatz-Tool, unabhängig vom JobFinder.

Nutzung:
    python3 stock_monitor.py              # ein Prüflauf (für Cron)
    python3 stock_monitor.py --test       # Prüflauf + Status aller URLs ausgeben, KEIN State/Alert
    python3 stock_monitor.py --get-chat-id  # ermittelt deine Telegram-Chat-ID
    python3 stock_monitor.py --notify-test  # schickt eine Telegram-Testnachricht

Konfiguration über Umgebungsvariablen bzw. die Datei .env im selben Ordner:
    TELEGRAM_BOT_TOKEN=123456:ABC...
    TELEGRAM_CHAT_ID=987654321
    NOTIFY_ON_ERROR=1     # optional: auch bei dauerhaften Abruf-Fehlern melden
"""

import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
ENV_FILE = BASE_DIR / ".env"
LOG_FILE = BASE_DIR / "monitor.log"

# Die zu überwachenden Seiten stehen in targets.json (zur Laufzeit über die
# Telegram-Befehle /add, /link, /del editierbar). Fehlt die Datei, wird sie aus
# diesen Defaults erzeugt.
TARGETS_FILE = BASE_DIR / "targets.json"

# Auto/Manual-Einträge sind Paare [Name, URL]. Standard beim ersten Start:
DEFAULT_AUTO = [
    ["OBI", "https://www.obi.de/p/8620890/midea-mobile-split-klimaanlage-portasplit?preselectedKp=true"],
    ["expert", "https://www.expert.de/shop/unsere-produkte/haushalt-kuche/wohnklima/klimagerate/32750011559-portasplit-mobile-split-klimaanlage.html"],
    ["Bauhaus", "https://www.bauhaus.info/klimaanlagen/midea-klimasplitgeraet-portasplit/p/31934233"],
]

# Seiten, die NICHT automatisch geprüft werden können (z.B. MediaMarkt: blockt
# die Server-IP per Cloudflare-CAPTCHA). Ihr Link wird ans Ende jeder
# Telegram-Nachricht gehängt, damit man sie manuell prüfen kann.
DEFAULT_MANUAL = [
    ["MediaMarkt", "https://www.mediamarkt.de/de/product/_midea-portasplit-cool-split-klimaanlage-weissgrau-max-raumgrosse-70-m-3035466.html"],
]


def _normalize_pairs(items):
    """Wandelt Einträge in [Name, URL]-Paare. Alte Form (nur URL-String) wird
    automatisch zu [abgeleiteter Name, URL] migriert."""
    pairs = []
    for item in items:
        if isinstance(item, str):
            pairs.append([site_name(item), item])
        elif item:
            name = item[0] if len(item) > 0 else ""
            url = item[1] if len(item) > 1 else ""
            pairs.append([name or site_name(url), url])
    return pairs


def load_targets():
    """Liest auto/manual-Listen aus targets.json (legt sie bei Bedarf an)."""
    if TARGETS_FILE.exists():
        try:
            d = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
            return {
                "auto": _normalize_pairs(d.get("auto", [])),
                "manual": _normalize_pairs(d.get("manual", [])),
            }
        except (json.JSONDecodeError, OSError):
            pass
    d = {"auto": [list(x) for x in DEFAULT_AUTO], "manual": [list(x) for x in DEFAULT_MANUAL]}
    save_targets(d)
    return d


def save_targets(d):
    TARGETS_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def get_auto():
    """Auto-Einträge als [Name, URL]-Paare."""
    return load_targets()["auto"]


def get_auto_urls():
    return [url for _name, url in load_targets()["auto"]]


def get_manual_urls():
    return load_targets()["manual"]

# Status-Werte
AVAILABLE = "AVAILABLE"      # online bestellbar
UNAVAILABLE = "UNAVAILABLE"  # nicht bestellbar (ausverkauft / nur Markt)
UNKNOWN = "UNKNOWN"          # Seite kam durch, aber kein eindeutiges Signal
BLOCKED = "BLOCKED"          # Cloudflare-Challenge -> automatisch zu „manuell prüfen"


# --------------------------------------------------------------------------- #
# .env laden (simpel, ohne Zusatzpaket)
# --------------------------------------------------------------------------- #
def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #
def telegram_api(method, params, timeout=30):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ist nicht gesetzt (.env).")
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_telegram(text):
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID ist nicht gesetzt (.env).")
    res = telegram_api(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        },
    )
    if not res.get("ok"):
        log(f"Telegram-Fehler: {res}")
    return res


def get_chat_id():
    """Liest die letzte eingehende Nachricht aus und zeigt die Chat-ID."""
    res = telegram_api("getUpdates", {})
    updates = res.get("result", [])
    if not updates:
        print(
            "Keine Nachrichten gefunden.\n"
            "→ Öffne deinen Bot in Telegram und schicke ihm einmal eine Nachricht "
            "(z. B. 'hallo'), dann diesen Befehl erneut ausführen."
        )
        return
    seen = {}
    for upd in updates:
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat", {})
        if chat.get("id") is not None:
            seen[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name", "")
    print("Gefundene Chats:")
    for cid, name in seen.items():
        print(f"  TELEGRAM_CHAT_ID={cid}   ({name})")


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Seiten abrufen (Playwright) + Status erkennen
# --------------------------------------------------------------------------- #
def fetch_pages(urls):
    """Rendert alle URLs mit einem Headless-Chromium und gibt {url: html} zurück."""
    from playwright.sync_api import sync_playwright

    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            },
        )
        # Stealth: typische Headless-Merkmale verstecken, damit Cloudflare die
        # JS-Challenge automatisch durchlässt statt CAPTCHA zu zeigen.
        context.add_init_script(STEALTH_JS)
        page = context.new_page()
        for url in urls:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                # Cookie-Banner best-effort wegklicken (verschiedene Schreibweisen)
                dismiss_cookies(page)
                # kurz auf Nachladen warten
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(800)
                html = page.content()
                # Cloudflare-„Nur einen Moment…"-Challenge kurz aussitzen: löst sich
                # nur, wenn überhaupt, in wenigen Sekunden. Harte Blocks lösen sich
                # nie -> nicht ewig warten (sonst dauert /check Minuten).
                waited = 0
                while is_challenge(html) and waited < 12000:
                    page.wait_for_timeout(4000)
                    waited += 4000
                    html = page.content()
                if is_challenge(html):
                    log(f"Challenge nicht überwunden: {url}")
                results[url] = html
            except Exception as exc:  # noqa: BLE001
                log(f"Abruf-Fehler {url}: {exc}")
                results[url] = ""
        browser.close()
    return results


# Init-Script gegen Bot-Erkennung (vor jedem Seitenaufbau injiziert).
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['de-DE','de','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = { runtime: {} };
const _q = window.navigator.permissions && window.navigator.permissions.query;
if (_q) {
  window.navigator.permissions.query = (p) =>
    p && p.name === 'notifications'
      ? Promise.resolve({state: Notification.permission})
      : _q(p);
}
"""

def is_challenge(html):
    """Erkennt die Cloudflare-Interstitial-/Warteseite (statt echtem Inhalt).

    Nur der Seitentitel ist zuverlässig: die Warteseite heißt „Nur einen Moment…"
    bzw. „Just a moment…". Generische Marker wie 'challenge-platform' oder
    '/cdn-cgi/' stehen auch auf ECHTEN Cloudflare-Seiten (z.B. expert.de) und
    taugen daher nicht zur Erkennung.
    """
    if not html:
        return False
    low = html.lower()
    return (
        "<title>nur einen moment" in low
        or "<title>just a moment" in low
        or "<title>einen moment" in low
        or "checking your browser before accessing" in low
    )


def dismiss_cookies(page):
    selectors = [
        "button#onetrust-accept-btn-handler",
        "button[data-testid='uc-accept-all-button']",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Alle Cookies akzeptieren')",
        "button:has-text('Zustimmen')",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def jsonld_availabilities(html):
    """Alle schema.org-availability-Werte aus dem HTML (JSON-LD + inline JSON)."""
    vals = re.findall(r'"availability"\s*:\s*"([^"]+)"', html)
    return [v.split("/")[-1].lower() for v in vals]  # z.B. 'instock', 'outofstock'


def detect_status(url, html):
    """Bestimmt den Bestell-Status einer Seite. Gibt (status, detail) zurück."""
    if not html:
        return UNKNOWN, "kein Inhalt (blockiert/Fehler)"
    if is_challenge(html):
        return BLOCKED, "Cloudflare-Challenge"

    host = urllib.parse.urlparse(url).netloc.lower()
    avails = jsonld_availabilities(html)
    low = html.lower()

    POSITIVE = {"instock", "limitedavailability", "onlineonly", "presale"}
    NEGATIVE = {"outofstock", "soldout", "instoreonly", "discontinued", "backorder"}

    # 1) schema.org-Signal hat Vorrang, wenn eindeutig
    has_pos = any(a in POSITIVE for a in avails)
    has_neg = any(a in NEGATIVE for a in avails)
    if has_pos and not has_neg:
        return AVAILABLE, f"JSON-LD: {','.join(sorted(set(avails)))}"
    if has_neg and not has_pos:
        return UNAVAILABLE, f"JSON-LD: {','.join(sorted(set(avails)))}"

    # 2) Heuristik über sichtbare Texte / Buttons
    neg_phrases = [
        "benachrichtig", "ausverkauft", "nicht verfügbar", "nicht lieferbar",
        "derzeit nicht", "vergriffen", "out of stock",
    ]
    pos_phrases = ["in den warenkorb", "in den einkaufswagen", "jetzt kaufen", "sofort lieferbar"]

    neg_hit = any(p in low for p in neg_phrases)
    pos_hit = any(p in low for p in pos_phrases)

    if pos_hit and not neg_hit:
        return AVAILABLE, "Text: Warenkorb/kaufen vorhanden"
    if neg_hit and not pos_hit:
        return UNAVAILABLE, "Text: ausverkauft/benachrichtigen"
    if neg_hit and pos_hit:
        # Beides vorhanden -> der Warenkorb-Button ist oft generisch im Markup
        # (z.B. Zubehör). 'Benachrichtigen'/'ausverkauft' überwiegt als klares Signal.
        return UNAVAILABLE, "Text: gemischt, ausverkauft-Signal dominiert"

    if avails:
        return UNKNOWN, f"JSON-LD uneindeutig: {','.join(sorted(set(avails)))}"
    return UNKNOWN, "kein eindeutiges Signal"


SITE_NAMES = {
    "obi.de": "OBI",
    "expert.de": "expert",
    "bauhaus.info": "Bauhaus",
    "mediamarkt.de": "MediaMarkt",
}


def site_name(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    for key, name in SITE_NAMES.items():
        if key in host:
            return name
    return host


# --------------------------------------------------------------------------- #
# Hauptlauf
# --------------------------------------------------------------------------- #
def check_all():
    """Prüft alle URLs und gibt eine Liste mit {url,name,status,detail} zurück."""
    auto = get_auto()  # [[name, url], ...]
    urls = [url for _n, url in auto]
    pages = fetch_pages(urls)
    results = []
    for name, url in auto:
        status, detail = detect_status(url, pages.get(url, ""))
        results.append(
            {"url": url, "name": name, "status": status, "detail": detail}
        )

    # Zweiter Versuch nur für unklare Seiten (Seite kam durch, aber kein Signal –
    # oft ein Ladeaussetzer). BLOCKED-Seiten werden NICHT erneut versucht: das
    # Aussitzen wurde gerade schon gemacht und verdoppelt sonst nur die Wartezeit.
    retry_urls = [r["url"] for r in results if r["status"] == UNKNOWN]
    if retry_urls:
        log(f"Re-Check für {len(retry_urls)} unklare Seite(n) …")
        pages2 = fetch_pages(retry_urls)
        for r in results:
            if r["url"] in retry_urls and pages2.get(r["url"]):
                status, detail = detect_status(r["url"], pages2[r["url"]])
                # Nur übernehmen, wenn der zweite Versuch ein klares Ergebnis bringt.
                if status in (AVAILABLE, UNAVAILABLE):
                    r["status"], r["detail"] = status, detail

    return results


STATUS_LABEL = {
    AVAILABLE: "✅ bestellbar",
    UNAVAILABLE: "⛔️ nicht bestellbar",
    UNKNOWN: "❓ nicht prüfbar",
}


def monitor_title():
    """Überschrift der Telegram-Nachrichten. Per .env (MONITOR_TITLE) anpassbar,
    da nicht mehr nur Klimaanlagen überwacht werden."""
    return os.environ.get("MONITOR_TITLE", "Verfügbarkeits-Check").strip() or "Verfügbarkeits-Check"


def manual_footer(results=None):
    """„Bitte manuell prüfen": konfigurierte manuelle Links + aktuell blockierte
    (Cloudflare) Auto-Seiten. Letztere wandern automatisch hier rein, solange sie
    geblockt sind – kommen sie wieder durch, erscheinen sie wieder als Status."""
    items = list(get_manual_urls())
    if results:
        for r in results:
            if r["status"] == BLOCKED:
                items.append([r["name"], r["url"]])
    if not items:
        return ""
    seen = set()
    lines = []
    for name, url in items:
        if url in seen:
            continue
        seen.add(url)
        lines.append(f'<a href="{url}">{name}</a>')
    return "\n\n— ✋ <b>bitte manuell prüfen</b> —\n" + "\n".join(lines)


def format_results(results):
    # Blockierte Seiten nicht als Status zeigen – sie stehen im manuellen Block.
    lines = []
    for r in results:
        if r["status"] == BLOCKED:
            continue
        label = STATUS_LABEL.get(r["status"], r["status"])
        lines.append(f"<b>{r['name']}</b> – {label}\n<a href=\"{r['url']}\">zur Seite</a>")
    body = "\n\n".join(lines) if lines else "(keine automatisch prüfbaren Seiten)"
    return f"🛒 <b>{monitor_title()} – aktueller Status</b>\n\n" + body + manual_footer(results)


def run(test_mode=False):
    state = {} if test_mode else load_state()
    results = check_all()
    alerts = []

    for r in results:
        url, name, status, detail = r["url"], r["name"], r["status"], r["detail"]
        prev = state.get(url, {}).get("status", UNKNOWN)
        log(f"{name:12s} {status:12s} ({detail})")

        if test_mode:
            continue

        # Alarm nur beim Übergang nach AVAILABLE (verhindert Dauer-Spam)
        if status == AVAILABLE and prev != AVAILABLE:
            alerts.append(f"✅ <b>{name}</b> ist jetzt bestellbar!\n{url}")

        # Optional: dauerhafte Fehler melden
        if (
            status == UNKNOWN
            and os.environ.get("NOTIFY_ON_ERROR") == "1"
            and prev != UNKNOWN
        ):
            alerts.append(f"⚠️ <b>{name}</b> nicht prüfbar ({detail})\n{url}")

        state[url] = {"status": status, "detail": detail, "ts": int(time.time())}

    if test_mode:
        return

    # Zeitpunkt des letzten automatischen Laufs merken (für /next).
    state["_meta"] = {"last_run": int(time.time())}
    save_state(state)

    if alerts:
        header = f"🛒 <b>{monitor_title()} – Verfügbarkeit</b>\n\n"
        try:
            send_telegram(header + "\n\n".join(alerts) + manual_footer(results))
            log(f"Telegram-Meldung gesendet ({len(alerts)} Treffer).")
        except Exception as exc:  # noqa: BLE001
            log(f"Konnte Telegram nicht senden: {exc}")
    elif os.environ.get("HEARTBEAT") == "1":
        # Lebenszeichen: bestätigt, dass der Job läuft, auch wenn nichts neu ist.
        try:
            send_telegram("🫀 Stündlicher Check – nichts Neues.\n\n" + format_results(results))
            log("Heartbeat-Meldung gesendet (nichts Neues).")
        except Exception as exc:  # noqa: BLE001
            log(f"Konnte Heartbeat nicht senden: {exc}")
    else:
        log("Keine neue Verfügbarkeit – keine Meldung.")


HELP_TEXT = (
    "🤖 <b>Stock-Monitor Bot</b>\n\n"
    "<b>Befehle:</b>\n"
    "/check – jetzt alle Seiten prüfen und Status anzeigen\n"
    "/next – letzten und nächsten automatischen Check anzeigen\n"
    "/list – überwachte &amp; manuelle Seiten auflisten\n"
    "/add &lt;link&gt; – neue Seite zur automatischen Prüfung hinzufügen\n"
    "/link &lt;link&gt; – neue Seite nur als manuellen Link (wie MediaMarkt)\n"
    "/edit – Name/URL eines Eintrags über Auswahlmenü ändern\n"
    "/del – Eintrag über Auswahlmenü löschen\n"
    "/help – diese Hilfe\n\n"
    "Außerdem melde ich mich automatisch, sobald ein Artikel wieder bestellbar wird."
)

BOT_COMMANDS = [
    {"command": "check", "description": "Jetzt alle Seiten prüfen"},
    {"command": "next", "description": "Letzten & nächsten Check anzeigen"},
    {"command": "list", "description": "Überwachte & manuelle Seiten anzeigen"},
    {"command": "add", "description": "Seite zur Auto-Prüfung hinzufügen (/add <link>)"},
    {"command": "link", "description": "Seite nur als manuellen Link (/link <link>)"},
    {"command": "edit", "description": "Name/URL eines Eintrags ändern (Auswahlmenü)"},
    {"command": "del", "description": "Eintrag löschen (Auswahlmenü)"},
    {"command": "help", "description": "Hilfe anzeigen"},
]


def tg_send(text, reply_markup=None, chat_id=None):
    """sendMessage mit optionalem Inline-Keyboard."""
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if reply_markup is not None:
        params["reply_markup"] = json.dumps(reply_markup)
    return telegram_api("sendMessage", params)


def is_valid_url(s):
    return s.startswith("http://") or s.startswith("https://")


def _fmt_time(ts):
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))


def _human_delta(sec):
    sec = abs(int(sec))
    if sec < 60:
        return f"{sec} Sek"
    if sec < 3600:
        return f"{sec // 60} Min"
    if sec < 86400:
        return f"{sec // 3600} Std {(sec % 3600) // 60} Min"
    return f"{sec // 86400} Tg"


def next_check_ts():
    """Nächster geplanter Cron-Lauf (stündlich zur Minute CRON_MINUTE, Default 0)."""
    minute = int(os.environ.get("CRON_MINUTE", "0"))
    now = time.time()
    lt = time.localtime(now)
    cand = time.struct_time(
        (lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, minute, 0,
         lt.tm_wday, lt.tm_yday, lt.tm_isdst)
    )
    cand_sec = time.mktime(cand)
    if cand_sec <= now:
        cand_sec += 3600
    return cand_sec


def cmd_next():
    """Zeigt letzten und nächsten automatischen Check."""
    st = load_state()
    last = st.get("_meta", {}).get("last_run")
    now = time.time()
    lines = ["🕒 <b>Check-Zeiten</b>"]
    if last:
        lines.append(f"Letzter Lauf: {_fmt_time(last)}  (vor {_human_delta(now - last)})")
    else:
        lines.append("Letzter Lauf: noch keiner (oder Cron läuft noch nicht)")
    nxt = next_check_ts()
    lines.append(f"Nächster Lauf: {_fmt_time(nxt)}  (in {_human_delta(nxt - now)})")
    lines.append("\n<i>Plan: stündlich. Falls dein Cron anders läuft, mit CRON_MINUTE anpassen.</i>")
    return "\n".join(lines)


def cmd_list():
    """Textübersicht aller Einträge."""
    t = load_targets()
    parts = ["📋 <b>Überwachte Seiten</b>"]
    if t["auto"]:
        parts += [f"🔎 <b>{n}</b>\n<a href=\"{u}\">{u}</a>" for n, u in t["auto"]]
    else:
        parts.append("(keine)")
    parts.append("\n✋ <b>Nur manueller Link</b>")
    if t["manual"]:
        parts += [f"<b>{n}</b>\n<a href=\"{u}\">{u}</a>" for n, u in t["manual"]]
    else:
        parts.append("(keine)")
    return "\n\n".join(parts)


def _entry_keyboard(action, prompt):
    """Inline-Keyboard mit allen Einträgen für eine Aktion (del/edit)."""
    t = load_targets()
    rows = []
    for i, (n, _u) in enumerate(t["auto"]):
        rows.append([{"text": f"🔎 {n} (auto)", "callback_data": f"{action}:a:{i}"}])
    for i, (n, _u) in enumerate(t["manual"]):
        rows.append([{"text": f"✋ {n} (manuell)", "callback_data": f"{action}:m:{i}"}])
    if not rows:
        return None, None
    rows.append([{"text": "✖️ Abbrechen", "callback_data": f"{action}:x:0"}])
    return {"inline_keyboard": rows}, prompt


_check_busy = False  # läuft gerade ein /check im Hintergrund?


def _run_check_async():
    """Führt einen Check aus und schickt das Ergebnis – im Hintergrund-Thread,
    damit der Bot während der ~1 min Prüfdauer weiter auf Befehle reagiert."""
    global _check_busy
    try:
        results = check_all()
        for r in results:
            log(f"[bot] {r['name']:12s} {r['status']}")
        tg_send(format_results(results))
    except Exception as exc:  # noqa: BLE001
        log(f"/check-Fehler: {exc}")
        try:
            tg_send(f"⚠️ Fehler bei der Prüfung: {exc}")
        except Exception:
            pass
    finally:
        _check_busy = False


def handle_command(cmd, arg):
    """Verarbeitet einen Textbefehl. Gibt nichts zurück (sendet selbst)."""
    global _check_busy
    if cmd in ("/check", "/status", "check", "status"):
        if _check_busy:
            tg_send("⏳ Eine Prüfung läuft schon – das Ergebnis kommt gleich.")
            return
        _check_busy = True
        tg_send("⏳ Prüfe alle Seiten … Ergebnis folgt in Kürze.")
        threading.Thread(target=_run_check_async, daemon=True).start()

    elif cmd in ("/list", "list"):
        tg_send(cmd_list())

    elif cmd in ("/next", "next", "/zeit", "zeit"):
        tg_send(cmd_next())

    elif cmd in ("/add", "add"):
        if not is_valid_url(arg):
            tg_send("So geht's: <code>/add https://…</code>")
            return
        t = load_targets()
        if any(u == arg for _n, u in t["auto"]):
            tg_send("Diese Seite wird bereits überwacht.")
            return
        name = site_name(arg)
        t["auto"].append([name, arg])
        save_targets(t)
        log(f"[bot] /add {arg}")
        tg_send(f"➕ Zur Auto-Prüfung hinzugefügt: <b>{name}</b>\nMit /check sofort testen, mit /edit umbenennen.")

    elif cmd in ("/link", "link"):
        if not is_valid_url(arg):
            tg_send("So geht's: <code>/link https://…</code>")
            return
        t = load_targets()
        if any(u == arg for _n, u in t["manual"]):
            tg_send("Dieser manuelle Link existiert bereits.")
            return
        name = site_name(arg)
        t["manual"].append([name, arg])
        save_targets(t)
        log(f"[bot] /link {arg}")
        tg_send(f"✋ Als manuellen Link angelegt: <b>{name}</b>")

    elif cmd in ("/del", "del", "/delete"):
        kb, prompt = _entry_keyboard("del", "Welchen Eintrag möchtest du löschen?")
        if kb is None:
            tg_send("Es gibt keine Einträge zum Löschen.")
        else:
            tg_send(prompt, reply_markup=kb)

    elif cmd in ("/edit", "edit"):
        kb, prompt = _entry_keyboard("edit", "Welchen Eintrag möchtest du bearbeiten?")
        if kb is None:
            tg_send("Es gibt keine Einträge zum Bearbeiten.")
        else:
            tg_send(prompt, reply_markup=kb)

    elif cmd in ("/start", "/help", "help", "start"):
        tg_send(HELP_TEXT)

    elif cmd:
        tg_send("Unbekannter Befehl. /help zeigt alle Befehle.")


def apply_edit(pending, value):
    """Wendet eine ausstehende Bearbeitung an. value: 'Name | URL', nur Name
    oder nur URL. Gibt eine Status-Nachricht zurück."""
    kind, idx = pending
    t = load_targets()
    lst = t["auto"] if kind == "a" else t["manual"]
    if not (0 <= idx < len(lst)):
        return "Eintrag nicht mehr vorhanden (Liste hat sich geändert)."

    name, url = lst[idx]
    value = value.strip()
    if "|" in value:
        new_name, new_url = value.split("|", 1)
        new_name, new_url = new_name.strip(), new_url.strip()
        if new_name:
            name = new_name
        if new_url:
            if not is_valid_url(new_url):
                return "URL muss mit http:// oder https:// beginnen. Nichts geändert."
            url = new_url
    elif is_valid_url(value):
        url = value
    elif value:
        name = value  # nur Name geändert

    lst[idx] = [name, url]
    save_targets(t)
    log(f"[bot] bearbeitet ({kind}): {name} -> {url}")
    return f"✏️ Geändert: <b>{name}</b>\n<a href=\"{url}\">{url}</a>"


def handle_callback(cb, allow):
    """Verarbeitet einen Knopfdruck (Auswahlmenü von /del und /edit).

    Rückgabe: bei /edit ein ('a'|'m', idx)-Tupel als ausstehende Bearbeitung,
    sonst None.
    """
    cb_id = cb.get("id")
    data = cb.get("data", "")
    message = cb.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    msg_id = message.get("message_id")

    if chat_id != allow:
        telegram_api("answerCallbackQuery", {"callback_query_id": cb_id})
        return None

    try:
        action, kind, idx = data.split(":")
        idx = int(idx)
    except ValueError:
        action, kind, idx = "del", "x", 0

    pending = None
    note = "Nichts geändert."

    if kind == "x":
        note = "Abgebrochen."
    elif action == "edit":
        t = load_targets()
        lst = t["auto"] if kind == "a" else t["manual"]
        if 0 <= idx < len(lst):
            name, url = lst[idx]
            pending = (kind, idx)
            note = (
                f"✏️ <b>{name}</b> bearbeiten.\n\n"
                "Schick mir jetzt den neuen Eintrag als:\n"
                "<code>Name | https://…</code>\n\n"
                "Oder nur eine neue URL, oder nur einen neuen Namen."
            )
        else:
            note = "Eintrag nicht mehr vorhanden (Liste hat sich geändert)."
    else:  # del
        t = load_targets()
        lst = t["auto"] if kind == "a" else t["manual"]
        if 0 <= idx < len(lst):
            removed = lst.pop(idx)
            save_targets(t)
            note = f"🗑 Gelöscht: {removed[0]}"
            log(f"[bot] gelöscht ({kind}): {removed}")
        else:
            note = "Eintrag nicht mehr vorhanden (Liste hat sich geändert)."

    # Beide Aufrufe fehlertolerant: eine „zu alte" Callback-Query (HTTP 400) darf
    # die Bearbeitung (ist bereits gespeichert) nicht als Fehler hochblasen.
    try:
        telegram_api("answerCallbackQuery", {"callback_query_id": cb_id})
    except Exception:
        pass
    if msg_id is not None:
        try:
            telegram_api(
                "editMessageText",
                {"chat_id": chat_id, "message_id": msg_id, "text": note,
                 "parse_mode": "HTML", "disable_web_page_preview": "true"},
            )
        except Exception:
            pass
    return pending


def run_bot():
    """Long-Polling-Loop: lauscht auf Telegram-Befehle und /del-Knöpfe."""
    allow = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not allow:
        raise RuntimeError("TELEGRAM_CHAT_ID muss gesetzt sein (.env).")
    log("Bot gestartet – warte auf Befehle (/check, /add, /link, /del, /list, /help).")
    try:
        telegram_api("setMyCommands", {"commands": json.dumps(BOT_COMMANDS)})
    except Exception as exc:  # noqa: BLE001
        log(f"setMyCommands fehlgeschlagen: {exc}")
    try:
        tg_send("🤖 Stock-Monitor Bot ist online. /help zeigt alle Befehle.")
    except Exception as exc:  # noqa: BLE001
        log(f"Start-Nachricht fehlgeschlagen: {exc}")

    offset = None
    pending_edit = None  # ('a'|'m', idx) während einer /edit-Folgeeingabe
    while True:
        try:
            params = {"timeout": 50}
            if offset is not None:
                params["offset"] = offset
            res = telegram_api("getUpdates", params, timeout=70)
        except Exception as exc:  # noqa: BLE001
            log(f"getUpdates-Fehler: {exc}")
            time.sleep(5)
            continue

        for upd in res.get("result", []):
            offset = upd["update_id"] + 1

            cb = upd.get("callback_query")
            if cb:
                try:
                    pending_edit = handle_callback(cb, allow) or pending_edit
                except Exception as exc:  # noqa: BLE001
                    log(f"Callback-Fehler: {exc}")
                continue

            msg = upd.get("message") or upd.get("edited_message") or {}
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if chat_id != allow:
                log(f"Ignoriere Nachricht von fremdem Chat {chat_id}.")
                continue

            raw = (msg.get("text") or "").strip()
            if not raw:
                continue

            # Folgeeingabe einer ausstehenden /edit-Bearbeitung (kein Befehl)?
            if pending_edit and not raw.startswith("/"):
                try:
                    tg_send(apply_edit(pending_edit, raw))
                except Exception as exc:  # noqa: BLE001
                    log(f"Edit-Fehler: {exc}")
                    tg_send(f"⚠️ Fehler beim Ändern: {exc}")
                pending_edit = None
                continue

            pending_edit = None  # ein echter Befehl bricht eine offene Bearbeitung ab
            parts = raw.split(maxsplit=1)
            cmd = parts[0].lower().split("@")[0]
            arg = parts[1].strip() if len(parts) > 1 else ""

            try:
                handle_command(cmd, arg)
            except Exception as exc:  # noqa: BLE001
                log(f"Befehls-Fehler ({cmd}): {exc}")
                try:
                    tg_send(f"⚠️ Fehler: {exc}")
                except Exception:
                    pass


def main():
    load_env()
    args = set(sys.argv[1:])

    if "--bot" in args:
        run_bot()
        return
    if "--debug" in args:
        urls = get_auto_urls()
        pages = fetch_pages(urls)
        for url in urls:
            html = pages.get(url, "")
            status, detail = detect_status(url, html)
            name = site_name(url)
            out = BASE_DIR / f"debug-{name}.html"
            out.write_text(html, encoding="utf-8")
            print(f"{name:12s} {status:12s} ({detail})  [{len(html)} Bytes -> {out.name}]")
        return

    if "--get-chat-id" in args:
        get_chat_id()
        return
    if "--notify-test" in args:
        send_telegram("✅ Stock-Monitor Test: Telegram funktioniert.")
        print("Testnachricht gesendet.")
        return

    run(test_mode="--test" in args)


if __name__ == "__main__":
    main()
