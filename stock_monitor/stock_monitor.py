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
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
ENV_FILE = BASE_DIR / ".env"
LOG_FILE = BASE_DIR / "monitor.log"

# Zu überwachende Produktseiten.
URLS = [
    "https://www.obi.de/p/8620890/midea-mobile-split-klimaanlage-portasplit?preselectedKp=true",
    "https://www.expert.de/shop/unsere-produkte/haushalt-kuche/wohnklima/klimagerate/32750011559-portasplit-mobile-split-klimaanlage.html",
    "https://www.bauhaus.info/klimaanlagen/midea-klimasplitgeraet-portasplit/p/31934233",
    "https://www.mediamarkt.de/de/product/_midea-portasplit-cool-split-klimaanlage-weissgrau-max-raumgrosse-70-m-3035466.html",
]

# Status-Werte
AVAILABLE = "AVAILABLE"      # online bestellbar
UNAVAILABLE = "UNAVAILABLE"  # nicht bestellbar (ausverkauft / nur Markt)
UNKNOWN = "UNKNOWN"          # konnte nicht ermittelt werden (Block/Fehler)


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
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
                html = page.content()
                # Cloudflare-„Nur einen Moment…"-Challenge aussitzen: sie löst sich
                # bei einem echt wirkenden Browser nach ein paar Sekunden selbst.
                waited = 0
                while is_challenge(html) and waited < 35000:
                    page.wait_for_timeout(5000)
                    waited += 5000
                    dismiss_cookies(page)
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

CHALLENGE_MARKERS = [
    "nur einen moment",
    "just a moment",
    "checking your browser",
    "challenge-platform",
    "/cdn-cgi/challenge",
    "cf-chl",
]


def is_challenge(html):
    """Erkennt eine Cloudflare-Interstitial-/Challenge-Seite (statt echtem Inhalt)."""
    if not html:
        return False
    low = html.lower()
    return len(html) < 60000 and any(m in low for m in CHALLENGE_MARKERS)


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
    pages = fetch_pages(URLS)
    results = []
    for url in URLS:
        status, detail = detect_status(url, pages.get(url, ""))
        results.append(
            {"url": url, "name": site_name(url), "status": status, "detail": detail}
        )
    return results


STATUS_LABEL = {
    AVAILABLE: "✅ bestellbar",
    UNAVAILABLE: "⛔️ nicht bestellbar",
    UNKNOWN: "❓ nicht prüfbar",
}


def format_results(results):
    lines = []
    for r in results:
        label = STATUS_LABEL.get(r["status"], r["status"])
        lines.append(f"<b>{r['name']}</b> – {label}\n<a href=\"{r['url']}\">zur Seite</a>")
    return "🛒 <b>Klimaanlage – aktueller Status</b>\n\n" + "\n\n".join(lines)


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

    save_state(state)

    if alerts:
        header = "🛒 <b>Klimaanlage – Verfügbarkeit</b>\n\n"
        try:
            send_telegram(header + "\n\n".join(alerts))
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
    "Befehle:\n"
    "/check – jetzt alle vier Seiten prüfen und Status anzeigen\n"
    "/help – diese Hilfe\n\n"
    "Außerdem melde ich mich automatisch, sobald ein Artikel wieder bestellbar wird."
)


def run_bot():
    """Long-Polling-Loop: lauscht auf Telegram-Befehle wie /check."""
    allow = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not allow:
        raise RuntimeError("TELEGRAM_CHAT_ID muss gesetzt sein (.env).")
    log("Bot gestartet – warte auf Befehle (/check, /help).")
    try:
        send_telegram("🤖 Stock-Monitor Bot ist online. Schick /check für eine Sofort-Prüfung.")
    except Exception as exc:  # noqa: BLE001
        log(f"Start-Nachricht fehlgeschlagen: {exc}")

    offset = None
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
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat", {})
            chat_id = str(chat.get("id", ""))
            text = (msg.get("text") or "").strip().lower()
            # /command@botname -> command
            cmd = text.split()[0].split("@")[0] if text else ""

            if chat_id != allow:
                log(f"Ignoriere Nachricht von fremdem Chat {chat_id}.")
                continue

            if cmd in ("/check", "/status", "check", "status"):
                try:
                    telegram_api(
                        "sendMessage",
                        {"chat_id": allow, "text": "⏳ Prüfe alle vier Seiten …"},
                    )
                    results = check_all()
                    for r in results:
                        log(f"[bot] {r['name']:12s} {r['status']}")
                    send_telegram(format_results(results))
                except Exception as exc:  # noqa: BLE001
                    log(f"/check-Fehler: {exc}")
                    try:
                        send_telegram(f"⚠️ Fehler bei der Prüfung: {exc}")
                    except Exception:
                        pass
            elif cmd in ("/start", "/help", "help", "start"):
                send_telegram(HELP_TEXT)
            elif cmd:
                send_telegram("Unbekannter Befehl. /check oder /help")


def main():
    load_env()
    args = set(sys.argv[1:])

    if "--bot" in args:
        run_bot()
        return
    if "--debug" in args:
        pages = fetch_pages(URLS)
        for url in URLS:
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
