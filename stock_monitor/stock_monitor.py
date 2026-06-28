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
def telegram_api(method, params):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ist nicht gesetzt (.env).")
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
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
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="de-DE",
            viewport={"width": 1366, "height": 900},
        )
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
                results[url] = page.content()
            except Exception as exc:  # noqa: BLE001
                log(f"Abruf-Fehler {url}: {exc}")
                results[url] = ""
        browser.close()
    return results


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
def run(test_mode=False):
    state = {} if test_mode else load_state()
    pages = fetch_pages(URLS)
    alerts = []

    for url in URLS:
        status, detail = detect_status(url, pages.get(url, ""))
        name = site_name(url)
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
    else:
        log("Keine neue Verfügbarkeit – keine Meldung.")


def main():
    load_env()
    args = set(sys.argv[1:])

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
