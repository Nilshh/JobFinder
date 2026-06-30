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
    """Liest auto/manual-Listen aus targets.json (legt sie bei Bedarf an).
    price_max: {url: float} – optionale Preisschwellen für den Preisalarm."""
    if TARGETS_FILE.exists():
        try:
            d = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
            return {
                "auto": _normalize_pairs(d.get("auto", [])),
                "manual": _normalize_pairs(d.get("manual", [])),
                "price_max": dict(d.get("price_max", {})),
            }
        except (json.JSONDecodeError, OSError):
            pass
    d = {
        "auto": [list(x) for x in DEFAULT_AUTO],
        "manual": [list(x) for x in DEFAULT_MANUAL],
        "price_max": {},
    }
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
def _fetch_chunk(urls):
    """Rendert eine Teilmenge URLs mit EINEM Headless-Chromium (eigene Playwright-
    Instanz, damit es thread-sicher parallel laufen kann). Gibt {url: html} zurück."""
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


def fetch_pages(urls):
    """Lädt alle URLs und gibt {url: html} zurück. Mehrere Seiten werden parallel
    in mehreren Browsern geladen (Anzahl via CHECK_WORKERS, Standard 4)."""
    urls = list(urls)
    if not urls:
        return {}
    try:
        max_workers = max(1, int(os.environ.get("CHECK_WORKERS", "4")))
    except ValueError:
        max_workers = 4
    if len(urls) == 1 or max_workers == 1:
        return _fetch_chunk(urls)

    from concurrent.futures import ThreadPoolExecutor

    n = min(max_workers, len(urls))
    chunks = [urls[i::n] for i in range(n)]  # gleichmäßig verteilen
    results = {}
    with ThreadPoolExecutor(max_workers=n) as ex:
        for part in ex.map(_fetch_chunk, chunks):
            results.update(part)
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
    title_markers = (
        "<title>nur einen moment",   # Cloudflare DE
        "<title>just a moment",      # Cloudflare EN
        "<title>einen moment",
        "<title>sicherheitscheck",   # z.B. prosatech.de
        "<title>security check",
        "<title>bot detection",
        "<title>access denied",
        "<title>zugriff verweigert",
    )
    return any(m in low for m in title_markers) or "checking your browser before accessing" in low


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


def extract_price(html):
    """Versucht, den Preis aus dem HTML zu lesen (schema.org 'price'/'lowPrice').
    Gibt einen float (in der Shop-Währung, i.d.R. EUR) zurück oder None."""
    if not html:
        return None
    candidates = []
    for key in ("price", "lowPrice", "highPrice"):
        for m in re.findall(rf'"{key}"\s*:\s*"?([0-9]+(?:[.,][0-9]{{1,2}})?)"?', html):
            try:
                candidates.append(float(m.replace(",", ".")))
            except ValueError:
                continue
    # Plausible Preise (>0); kleinster Treffer ist meist der Artikelpreis
    candidates = [c for c in candidates if c > 0]
    return min(candidates) if candidates else None


def fmt_price(price):
    if price is None:
        return ""
    return f"{price:.2f} €".replace(".", ",")


def detect_status(url, html):
    """Bestimmt den Bestell-Status einer Seite. Gibt (status, detail) zurück."""
    if not html:
        return UNKNOWN, "kein Inhalt (blockiert/Fehler)"
    if is_challenge(html):
        return BLOCKED, "Bot-Sperre/Challenge"

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
        html = pages.get(url, "")
        status, detail = detect_status(url, html)
        results.append(
            {"url": url, "name": name, "status": status, "detail": detail,
             "price": extract_price(html)}
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
                    r["price"] = extract_price(pages2[r["url"]])

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


def heartbeat_interval_min():
    """Mindestabstand zwischen zwei Heartbeat-Meldungen (Default 60 Min), damit
    das Lebenszeichen nicht bei jedem Prüflauf (z.B. alle 10 Min) kommt."""
    try:
        return max(1, int(os.environ.get("HEARTBEAT_EVERY_MIN", "60")))
    except ValueError:
        return 60


def in_heartbeat_window():
    """True, wenn die aktuelle Stunde im Heartbeat-Fenster liegt (Ruhezeiten).
    Konfiguriert über HEARTBEAT_FROM/HEARTBEAT_TO (lokale Stunden, Default 8–22).
    Echte Verfügbarkeits-Alarme sind davon NICHT betroffen – nur das Lebenszeichen."""
    try:
        start = int(os.environ.get("HEARTBEAT_FROM", "8"))
        end = int(os.environ.get("HEARTBEAT_TO", "22"))
    except ValueError:
        start, end = 8, 22
    hour = time.localtime().tm_hour
    if start <= end:
        return start <= hour <= end
    # über Mitternacht, z.B. 22–6
    return hour >= start or hour <= end


def manual_footer(results=None):
    """„Bitte manuell prüfen": rein manuelle Links + aktuell blockierte Auto-Seiten.
    Auto-Seiten, die NICHT blockiert sind, erscheinen hier nie (sie stehen oben als
    Status) – auch wenn versehentlich ein doppelter manueller Eintrag existiert."""
    auto_urls = {url for _n, url in get_auto()}
    blocked_urls = {r["url"] for r in (results or []) if r["status"] == BLOCKED}

    items = []
    # Konfigurierte manuelle Links – aber keine, die als Auto-Seite gerade
    # normal (nicht blockiert) geprüft werden (verhindert Doppelanzeige).
    for name, url in get_manual_urls():
        if url in auto_urls and url not in blocked_urls:
            continue
        items.append([name, url])
    # Aktuell blockierte Auto-Seiten.
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
        # Falls der Name fehlt oder selbst eine URL ist: Domain als Bezeichnung.
        label = name if (name and not name.startswith("http")) else site_name(url)
        lines.append(f'<a href="{url}">{label}</a>')
    return "\n\n— ✋ <b>bitte manuell prüfen</b> —\n" + "\n".join(lines)


def format_results(results):
    # Blockierte Seiten nicht als Status zeigen – sie stehen im manuellen Block.
    price_max = load_targets().get("price_max", {})
    lines = []
    for r in results:
        if r["status"] == BLOCKED:
            continue
        label = STATUS_LABEL.get(r["status"], r["status"])
        extra = ""
        price = r.get("price")
        if price is not None:
            extra = f" · {fmt_price(price)}"
            limit = price_max.get(r["url"])
            if limit is not None:
                hit = "✅" if price <= float(limit) else "↧"
                extra += f" (Ziel {fmt_price(float(limit))} {hit})"
        lines.append(f"<b>{r['name']}</b> – {label}{extra}\n<a href=\"{r['url']}\">zur Seite</a>")
    body = "\n\n".join(lines) if lines else "(keine automatisch prüfbaren Seiten)"
    return f"🛒 <b>{monitor_title()} – aktueller Status</b>\n\n" + body + manual_footer(results)


def run(test_mode=False):
    state = {} if test_mode else load_state()
    results = check_all()
    price_max = load_targets().get("price_max", {})
    alerts = []

    for r in results:
        url, name, status, detail = r["url"], r["name"], r["status"], r["detail"]
        price = r.get("price")
        st_prev = state.get(url, {})
        prev = st_prev.get("status", UNKNOWN)
        prev_price = st_prev.get("price")
        log(f"{name:12s} {status:12s} ({detail})" + (f" {fmt_price(price)}" if price else ""))

        if test_mode:
            continue

        # Verfügbarkeits-Alarm: beim Wechsel auf bestellbar – und danach bei JEDEM
        # Lauf erneut (Wiederhol-Alarm), bis du /seen schickst. So verpasst du es
        # nicht, falls du einen Ping übersiehst. „ack" = quittiert.
        ack = st_prev.get("ack", False) if (status == AVAILABLE and prev == AVAILABLE) else False
        if status == AVAILABLE and not ack:
            if prev == AVAILABLE:
                line = f"🔁 <b>{name}</b> ist weiterhin bestellbar – /seen zum Stoppen"
            else:
                line = f"✅ <b>{name}</b> ist jetzt bestellbar!"
            if price is not None:
                line += f" ({fmt_price(price)})"
            alerts.append(line + f"\n{url}")

        # Preisalarm: Preis fällt auf/unter die gesetzte Schwelle (Übergang).
        limit = price_max.get(url)
        if limit is not None and price is not None:
            below = price <= float(limit)
            was_below = prev_price is not None and prev_price <= float(limit)
            if below and not was_below:
                alerts.append(
                    f"💶 <b>{name}</b> ist im Preis gefallen: {fmt_price(price)} "
                    f"(Ziel {fmt_price(float(limit))})\n{url}"
                )

        # Optional: dauerhafte Fehler melden
        if (
            status == UNKNOWN
            and os.environ.get("NOTIFY_ON_ERROR") == "1"
            and prev != UNKNOWN
        ):
            alerts.append(f"⚠️ <b>{name}</b> nicht prüfbar ({detail})\n{url}")

        state[url] = {"status": status, "detail": detail, "price": price,
                      "ack": ack, "ts": int(time.time())}

    if test_mode:
        return

    now = int(time.time())
    meta = state.get("_meta", {}) if isinstance(state.get("_meta"), dict) else {}
    meta["last_run"] = now  # für /next

    if alerts:
        header = f"🛒 <b>{monitor_title()} – Verfügbarkeit</b>\n\n"
        try:
            send_telegram(header + "\n\n".join(alerts) + manual_footer(results))
            log(f"Telegram-Meldung gesendet ({len(alerts)} Treffer).")
        except Exception as exc:  # noqa: BLE001
            log(f"Konnte Telegram nicht senden: {exc}")
    elif (
        os.environ.get("HEARTBEAT") == "1"
        and in_heartbeat_window()
        and now - meta.get("last_heartbeat", 0) >= heartbeat_interval_min() * 60
    ):
        # Lebenszeichen: bestätigt, dass der Job läuft – aber entkoppelt vom Prüf-
        # Takt (höchstens alle HEARTBEAT_EVERY_MIN Minuten), nicht bei jedem Lauf.
        try:
            send_telegram("🫀 Status – nichts Neues.\n\n" + format_results(results))
            meta["last_heartbeat"] = now
            log("Heartbeat-Meldung gesendet (nichts Neues).")
        except Exception as exc:  # noqa: BLE001
            log(f"Konnte Heartbeat nicht senden: {exc}")
    else:
        log("Keine neue Verfügbarkeit – keine Meldung.")

    state["_meta"] = meta
    save_state(state)


HELP_TEXT = (
    "🤖 <b>Stock-Monitor Bot</b>\n\n"
    "<b>Befehle:</b>\n"
    "/check – jetzt alle Seiten prüfen und Status anzeigen\n"
    "/next – letzten und nächsten automatischen Check anzeigen\n"
    "/list – überwachte &amp; manuelle Seiten auflisten\n"
    "/add &lt;Name&gt; | &lt;link&gt; – neue Seite zur automatischen Prüfung (Name optional)\n"
    "/link &lt;Name&gt; | &lt;link&gt; – neue Seite nur als manuellen Link (Name optional)\n"
    "/edit – Name/URL eines Eintrags über Auswahlmenü ändern\n"
    "/price – Preisalarm setzen (Auswahlmenü, dann Maximalpreis)\n"
    "/seen – Wiederhol-Alarme quittieren (stoppen)\n"
    "/del – Eintrag über Auswahlmenü löschen\n"
    "/help – diese Hilfe\n\n"
    "Sobald ein Artikel bestellbar wird, melde ich mich – und wiederhole die Meldung "
    "bei jedem Lauf, bis du /seen schickst. Außerdem bei Preis unter deinem Ziel."
)

BOT_COMMANDS = [
    {"command": "check", "description": "Jetzt alle Seiten prüfen"},
    {"command": "next", "description": "Letzten & nächsten Check anzeigen"},
    {"command": "list", "description": "Überwachte & manuelle Seiten anzeigen"},
    {"command": "add", "description": "Auto-Prüfung: /add Name | <link>"},
    {"command": "link", "description": "Manueller Link: /link Name | <link>"},
    {"command": "edit", "description": "Name/URL eines Eintrags ändern (Auswahlmenü)"},
    {"command": "price", "description": "Preisalarm setzen (Auswahlmenü)"},
    {"command": "seen", "description": "Wiederhol-Alarme quittieren/stoppen"},
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


def parse_name_url(arg):
    """Zerlegt '<Name> | <URL>' oder nur '<URL>' in (name, url).
    Ohne Namen wird die Domain genommen. (None, None) bei ungültiger URL."""
    arg = arg.strip()
    if "|" in arg:
        name, url = arg.split("|", 1)
        name, url = name.strip(), url.strip()
    else:
        name, url = "", arg.strip()
    if not is_valid_url(url):
        return None, None
    return (name or site_name(url)), url


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


def check_interval_minutes():
    try:
        return max(1, int(os.environ.get("CHECK_INTERVAL_MINUTES", "60")))
    except ValueError:
        return 60


def next_check_ts():
    """Nächster geplanter Lauf, abgeleitet aus dem Intervall (Slots ab Mitternacht).
    Z.B. Intervall 10 -> :00, :10, :20 … Muss zur Crontab passen (*/10)."""
    interval = check_interval_minutes()
    now = time.time()
    lt = time.localtime(now)
    mins_of_day = lt.tm_hour * 60 + lt.tm_min
    next_slot = ((mins_of_day // interval) + 1) * interval
    midnight = now - (mins_of_day * 60 + lt.tm_sec)
    return midnight + next_slot * 60


def cmd_next():
    """Zeigt letzten und nächsten automatischen Check."""
    st = load_state()
    last = st.get("_meta", {}).get("last_run")
    now = time.time()
    interval = check_interval_minutes()
    lines = ["🕒 <b>Check-Zeiten</b>"]
    if last:
        lines.append(f"Letzter Lauf: {_fmt_time(last)}  (vor {_human_delta(now - last)})")
    else:
        lines.append("Letzter Lauf: noch keiner (oder Cron läuft noch nicht)")
    nxt = next_check_ts()
    lines.append(f"Nächster Lauf: {_fmt_time(nxt)}  (in {_human_delta(nxt - now)})")
    lines.append(f"\n<i>Plan: alle {interval} Min. Muss zur Crontab passen (z.B. */{interval}).</i>")
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


def _check_one_async(name, url):
    """Prüft eine einzelne Seite (für die Sofort-Rückmeldung nach /add)."""
    try:
        html = fetch_pages([url]).get(url, "")
        status, detail = detect_status(url, html)
        price = extract_price(html)
        label = STATUS_LABEL.get(status, status)
        if status == BLOCKED:
            tg_send(
                f"✋ <b>{name}</b>: Seite ist durch Cloudflare blockiert – sie wird "
                "automatisch unter „manuell prüfen“ geführt (selbstheilend)."
            )
        elif status == UNKNOWN:
            tg_send(
                f"⚠️ <b>{name}</b>: Verfügbarkeit nicht erkennbar ({detail}). "
                "Wird trotzdem stündlich erneut versucht."
            )
        else:
            extra = f" · {fmt_price(price)}" if price is not None else ""
            tg_send(f"🔎 <b>{name}</b>: {label}{extra}")
    except Exception as exc:  # noqa: BLE001
        log(f"/add-Sofortcheck-Fehler: {exc}")


def apply_price(pending, value):
    """Setzt/entfernt die Preisschwelle für einen Eintrag. value: Zahl oder 0/aus."""
    kind, idx = pending
    t = load_targets()
    lst = t["auto"] if kind == "a" else t["manual"]
    if not (0 <= idx < len(lst)):
        return "Eintrag nicht mehr vorhanden (Liste hat sich geändert)."
    name, url = lst[idx]
    raw = value.strip().lower().replace("€", "").replace(",", ".").strip()
    if raw in ("0", "-", "aus", "off", "none", ""):
        t["price_max"].pop(url, None)
        save_targets(t)
        log(f"[bot] Preisalarm entfernt: {name}")
        return f"🔕 Preisalarm für <b>{name}</b> entfernt."
    try:
        v = float(raw)
    except ValueError:
        return "Bitte eine Zahl schicken, z.B. <code>999</code> oder <code>999,00</code> (0 = aus)."
    t["price_max"][url] = v
    save_targets(t)
    log(f"[bot] Preisalarm gesetzt: {name} <= {v}")
    return f"💶 Preisalarm gesetzt: <b>{name}</b> ≤ {fmt_price(v)}\nMeldung, sobald der Preis das erreicht."


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
        name, url = parse_name_url(arg)
        if not url:
            tg_send("So geht's: <code>/add Name | https://…</code>\n(oder nur die URL)")
            return
        t = load_targets()
        if any(u == url for _n, u in t["auto"]):
            tg_send("Diese Seite wird bereits überwacht.")
            return
        t["auto"].append([name, url])
        save_targets(t)
        log(f"[bot] /add {name} -> {url}")
        tg_send(f"➕ Zur Auto-Prüfung hinzugefügt: <b>{name}</b>\n⏳ Teste die Seite einmal …")
        threading.Thread(target=_check_one_async, args=(name, url), daemon=True).start()

    elif cmd in ("/link", "link"):
        name, url = parse_name_url(arg)
        if not url:
            tg_send("So geht's: <code>/link Name | https://…</code>\n(oder nur die URL)")
            return
        t = load_targets()
        if any(u == url for _n, u in t["manual"]):
            tg_send("Dieser manuelle Link existiert bereits.")
            return
        t["manual"].append([name, url])
        save_targets(t)
        log(f"[bot] /link {name} -> {url}")
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

    elif cmd in ("/price", "price", "/preis", "preis"):
        kb, prompt = _entry_keyboard("price", "Für welchen Eintrag einen Preisalarm setzen?")
        if kb is None:
            tg_send("Es gibt keine Einträge.")
        else:
            tg_send(prompt, reply_markup=kb)

    elif cmd in ("/seen", "seen", "/gesehen", "gesehen"):
        st = load_state()
        n = 0
        for v in st.values():
            if isinstance(v, dict) and v.get("status") == AVAILABLE and not v.get("ack"):
                v["ack"] = True
                n += 1
        save_state(st)
        if n:
            tg_send(f"✅ Quittiert – Wiederhol-Alarme für {n} Artikel gestoppt.")
        else:
            tg_send("Nichts zu quittieren (kein aktiver Bestellbar-Alarm).")

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
            pending = ("edit", kind, idx)
            note = (
                f"✏️ <b>{name}</b> bearbeiten.\n\n"
                "Schick mir jetzt den neuen Eintrag als:\n"
                "<code>Name | https://…</code>\n\n"
                "Oder nur eine neue URL, oder nur einen neuen Namen."
            )
        else:
            note = "Eintrag nicht mehr vorhanden (Liste hat sich geändert)."
    elif action == "price":
        t = load_targets()
        lst = t["auto"] if kind == "a" else t["manual"]
        if 0 <= idx < len(lst):
            name, url = lst[idx]
            pending = ("price", kind, idx)
            cur = t.get("price_max", {}).get(url)
            cur_txt = f"\n(aktuell: ≤ {fmt_price(float(cur))})" if cur is not None else ""
            note = (
                f"💶 Preisalarm für <b>{name}</b>.{cur_txt}\n\n"
                "Schick mir jetzt den <b>Maximalpreis</b> als Zahl (z.B. <code>999</code> "
                "oder <code>999,00</code>).\n<code>0</code> = Preisalarm aus."
            )
        else:
            note = "Eintrag nicht mehr vorhanden (Liste hat sich geändert)."
    else:  # del
        t = load_targets()
        lst = t["auto"] if kind == "a" else t["manual"]
        if 0 <= idx < len(lst):
            removed = lst.pop(idx)
            t.get("price_max", {}).pop(removed[1], None)  # ggf. Preisalarm mitlöschen
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
    pending = None  # ('edit'|'price', 'a'|'m', idx) während einer Folgeeingabe
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
                    pending = handle_callback(cb, allow) or pending
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

            # Folgeeingabe einer ausstehenden /edit- oder /price-Aktion (kein Befehl)?
            if pending and not raw.startswith("/"):
                action, kind, idx = pending
                try:
                    if action == "price":
                        tg_send(apply_price((kind, idx), raw))
                    else:
                        tg_send(apply_edit((kind, idx), raw))
                except Exception as exc:  # noqa: BLE001
                    log(f"Folgeeingabe-Fehler: {exc}")
                    tg_send(f"⚠️ Fehler: {exc}")
                pending = None
                continue

            pending = None  # ein echter Befehl bricht eine offene Aktion ab
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
