# Stock-Monitor (Zusatz-Tool)

Prüft stündlich vier Produktseiten der **Midea PortaSplit Klimaanlage** auf
**Online-Bestellbarkeit** und schickt eine **Telegram-Nachricht**, sobald ein
Artikel wieder bestellbar ist.

Eigenständig, unabhängig vom JobFinder. Liegt nur der Ordnung halber im selben Repo.

Überwacht:
- OBI · expert · Bauhaus · MediaMarkt

## Warum ein echter Browser?

Einfaches `requests`/`curl` reicht hier nicht:
- **Bauhaus** blockt mit Cloudflare (HTTP 403),
- **expert** lädt den Status per JavaScript nach.

Deshalb rendert das Tool die Seiten mit **Playwright/Chromium** (headless). Der
Status wird vorrangig aus dem `schema.org`-Feld `availability` (JSON-LD) gelesen,
ergänzt um eine Text-Heuristik („In den Warenkorb" vs. „Benachrichtigen/Ausverkauft").

Eine Meldung kommt **nur beim Wechsel** von *nicht bestellbar* → *bestellbar*
(kein stündlicher Spam).

---

## 1. Installation

```bash
cd stock_monitor
./setup.sh
```

Das legt eine virtuelle Umgebung `.venv` an, installiert Playwright + Chromium
und erstellt `.env` aus der Vorlage.

## 2. Telegram-Bot anlegen (Schritt für Schritt)

1. In Telegram **@BotFather** öffnen → `/newbot` senden.
2. Namen + Benutzernamen vergeben (Benutzername muss auf `bot` enden, z. B. `klima_alarm_bot`).
3. BotFather antwortet mit dem **Token** (Form `123456789:AAE...`). Diesen Token
   in `.env` bei `TELEGRAM_BOT_TOKEN` eintragen.
4. Deinen neuen Bot in Telegram öffnen und ihm einmal **irgendeine Nachricht**
   schicken (z. B. „hallo"). Das ist nötig, damit der Bot dir schreiben darf.
5. Chat-ID ermitteln:

   ```bash
   ./run.sh --get-chat-id
   ```

   Den ausgegebenen Wert bei `TELEGRAM_CHAT_ID` in `.env` eintragen.

6. Test verschicken:

   ```bash
   ./run.sh --notify-test
   ```

   Wenn die Nachricht in Telegram ankommt, passt alles.

## 3. Funktion testen

```bash
./run.sh --test
```

Zeigt den erkannten Status aller vier Seiten an, **ohne** etwas zu speichern oder
zu melden. So siehst du sofort, ob die Erkennung sauber greift.

## 4. Stündlich per Cron einrichten

Crontab öffnen:

```bash
crontab -e
```

Zeile einfügen (Pfad ggf. anpassen):

```cron
0 * * * * /Users/nils/Documents/GitHub/JobFinder/JobFinder/stock_monitor/run.sh >> /Users/nils/Documents/GitHub/JobFinder/JobFinder/stock_monitor/cron.log 2>&1
```

`0 * * * *` = jede volle Stunde. (Tipp zum Testen alle 15 Min: `*/15 * * * *`.)

> Hinweis macOS: Cron läuft nur, wenn der Rechner an ist. Soll es auch im
> Ruhezustand/zuverlässig laufen, sag Bescheid – dann liefere ich eine
> `launchd`-Variante (.plist).

---

## Dateien

| Datei | Zweck |
|---|---|
| `stock_monitor.py` | Hauptskript (Abruf, Erkennung, Telegram) |
| `run.sh` | Wrapper für Cron (nutzt `.venv`) |
| `setup.sh` | Einmalige Installation |
| `.env` | Deine Telegram-Zugangsdaten (nicht im Git) |
| `state.json` | Letzter bekannter Status je URL (Auto-generiert) |
| `monitor.log` | Verlaufsprotokoll |

## URLs ändern / erweitern

Liste `URLS` oben in `stock_monitor.py` anpassen. Die Erkennung ist generisch
(JSON-LD + Heuristik) und funktioniert i. d. R. auch bei weiteren Shops.
