# Stock-Monitor (Zusatz-Tool)

Prüft stündlich vier Produktseiten der **Midea PortaSplit Klimaanlage** auf
**Online-Bestellbarkeit** und schickt eine **Telegram-Nachricht**, sobald ein
Artikel wieder bestellbar ist.

Eigenständig, unabhängig vom JobFinder. Liegt nur der Ordnung halber im selben Repo.

Automatisch überwacht:
- OBI · expert · Bauhaus

Nur als Link (manuell): MediaMarkt – dessen Seite blockt fremde Server-IPs per
Cloudflare-CAPTCHA, lässt sich also nicht zuverlässig automatisch prüfen. Der
Link hängt deshalb am Ende jeder Telegram-Nachricht zum manuellen Nachsehen.
(Liste `MANUAL_URLS` in `stock_monitor.py`.)

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

**Lebenszeichen:** Standardmäßig meldet sich der Job nur, wenn etwas bestellbar
wird. Möchtest du stündlich auch dann eine kurze Status-Übersicht (um zu sehen,
dass er läuft), setze in `.env`:

```
HEARTBEAT=1
```

> Hinweis macOS: Cron läuft nur, wenn der Rechner an ist. Soll es auch im
> Ruhezustand/zuverlässig laufen, sag Bescheid – dann liefere ich eine
> `launchd`-Variante (.plist).

---

## 5. Sofort-Prüfung per Telegram (`/check`)

Zusätzlich zum stündlichen Auto-Alarm kann der Bot **auf Befehle reagieren**.
Du schickst ihm `/check` und bekommst sofort den aktuellen Status aller vier
Seiten zurück.

Dafür muss ein dauerhafter Prozess laufen (Long-Polling). Manuell zum Testen:

```bash
./run.sh --bot
```

Dann in Telegram an den Bot schreiben. Verfügbare Befehle:

| Befehl | Funktion |
|---|---|
| `/check` | Jetzt alle Seiten prüfen und Status anzeigen |
| `/list` | Überwachte und manuelle Seiten auflisten |
| `/add <link>` | Neue Seite zur **automatischen** Prüfung hinzufügen |
| `/link <link>` | Neue Seite nur als **manuellen** Link (wie MediaMarkt) |
| `/del` | Eintrag über ein Auswahlmenü (Knöpfe) löschen |
| `/help` | Hilfe anzeigen |

Die Listen werden in `targets.json` gespeichert (nicht im Git). Der stündliche
Cron-Lauf liest dieselbe Datei – Änderungen per Bot wirken also sofort auch auf
die automatischen Prüfungen.

### Als Dienst (systemd, empfohlen auf dem Server)

```bash
sudo cp stock-monitor-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stock-monitor-bot
sudo systemctl status stock-monitor-bot      # läuft?
journalctl -u stock-monitor-bot -f           # Live-Log
```

Der Bot-Dienst (getUpdates) und der Cron-Alarm (sendMessage) stören sich nicht –
beide dürfen parallel laufen.

> Hinweis: `--get-chat-id` und der Bot-Dienst können **nicht gleichzeitig** laufen
> (Telegram erlaubt nur einen getUpdates-Abnehmer). Chat-ID also vor dem Start des
> Dienstes ermitteln, oder den Dienst kurz stoppen.

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
