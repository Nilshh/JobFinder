# JobPipeline

> Vollständige Bewerbungs-Plattform mit Auto-Discovery, Search-Alerts, Company-Boards, KI-Anschreiben, Kanban-Pipeline, Karriere-Monitor, PWA, Web-Push, Jira-Integration und Mehrbenutzer-Unterstützung

JobPipeline ist eine installierbare Web-App (PWA) für die strukturierte Jobsuche und Bewerbungsverwaltung. Sie durchsucht **fünf Jobquellen** (Adzuna, Bundesagentur für Arbeit, Jobicy, RemoteOK, The Muse) parallel – inklusive automatischer **Synonym-Expansion** –, filtert bereits gespeicherte oder ignorierte Stellen automatisch heraus und verlinkt direkt auf **45+ Jobportale**.

**Drei automatisierte Such-Mechanismen im Hintergrund:**
- **Search-Alerts** führen deine Suchen regelmäßig aus und melden neue Treffer per E-Mail + Web-Push.
- **Karriere-Monitor** (Playwright) überwacht beliebige Unternehmens-Karriereseiten auf Keyword-Matches.
- **Company-Boards** (Greenhouse, Lever) holen strukturierte Job-Daten von Scale-ups wie Airbnb, Stripe oder Shopify.

**Vollständiger Bewerbungs-Workflow:**
- **Kanban-Pipeline** mit Drag&Drop für die Bewerbungsphasen
- **CV-Manager + Anschreiben-Vorlagen** mit Platzhaltern
- **KI-generierte Anschreiben** (Anthropic) basierend auf Job + Profil
- **Match-Score** je Job basierend auf deinem Profil
- **Interview-Termine** mit ICS-Export für den Kalender
- **Follow-up-Hinweise** für überfällige Bewerbungen

**Insights & Benachrichtigungen:**
- **Bewerbungs-Dashboard** mit Kennzahlen, Status-Verteilung, Top-Unternehmen
- **Salary-Insights** und **Skills-Heatmap** aus deinen Daten
- **Wöchentlicher Markt-Report** per E-Mail (Sonntags)
- **Web-Push-Benachrichtigungen** zusätzlich zu E-Mail
- **Jira-Export** mit einem Klick

---

## Features

### Jobsuche
- **Mehrfach-Titelsuche** — Vordefinierte Chips (CTO, CIO, CDO, Head of IT, Leiter IT u. a.) + eigene Titel
- **Parallele Suche** — Alle gewählten Jobtitel werden gleichzeitig an fünf Quellen abgefragt (Adzuna + BA + Jobicy + RemoteOK + The Muse)
- **Keyword-Synonyme** — Automatische Erweiterung um verwandte Begriffe (z. B. CTO → VP Engineering, Chief Technology Officer); per Toggle abschaltbar
- **Remote-Filter** — Nur Remote-Jobs anzeigen (Jobicy + RemoteOK + Adzuna-Remote-Filter)
- **Standort-Filter** — Ort, PLZ und Umkreis (10 / 25 / 50 / 100 / 150 km); optional bei Remote
- **Zeitfilter** — Letzte Woche / 2 Wochen / Monat / alle
- **Suchverlauf** — Letzte 15 Suchen werden gespeichert; Ein-Klick-Wiederholung mit allen Filtern
- **Suche abonnieren** — Jede Suche kann als wiederkehrender **Search-Alert** gespeichert werden (siehe unten)
- **Seitennavigation** — Ergebnisse seitenweise blättern (20 je Seite)
- **API-Caching** — Identische Suchen werden 5 Minuten gecacht (spart API-Quota, konfigurierbar)
- **DACH-Support** — Automatische Länder-Erkennung (DE / AT / CH)
- **Deduplication** — Bereits gespeicherte oder ignorierte Stellen werden ausgeblendet
- **Ignorier-Funktion** — Stellen einmalig wegklicken, tauchen bei nächster Suche nicht mehr auf
- **Ohne Anmeldung nutzbar** — Die Suche funktioniert auch ohne Account

### Merkzettel & Tracking
- **Speichern mit einem Klick** — Job landet sofort auf dem Merkzettel
- **Manueller Eintrag** — Eigene Stellenlinks ohne Suche direkt hinzufügen
- **Status-Tracking** — Neu · Interessant · Beworben · Abgelehnt · Angebot
- **Notizen** — Freies Textfeld je Stelle (Ansprechpartner, Gehaltsvorstellung, Gesprächsnotizen)
- **Status-Filter** — Merkzettel nach Bewerbungsstatus filtern
- **CSV-Export** — Alle gespeicherten Stellen als CSV herunterladen (Excel-kompatibel, UTF-8)
- **Serverseitige Persistenz** — Daten werden pro Benutzer in SQLite gespeichert

### Bewerbungs-Dashboard
Visueller Überblick über den Bewerbungsprozess:
- **Kennzahlen** — Gesamt gespeichert, Beworben, Angebote, Ablehnungen, Erfolgsquote
- **Status-Verteilung** — Farbcodierter Balken über alle Status
- **Timeline** — Gespeicherte Jobs pro Woche (letzte 8 Wochen)
- **Top-Unternehmen** — Die 5 Firmen mit den meisten gespeicherten Stellen
- **Rein clientseitig** — Keine zusätzlichen Abhängigkeiten, berechnet aus vorhandenen Daten

### Search-Alerts (gespeicherte Suchen)
Deine Suchen werden im Hintergrund automatisch wiederholt und melden neue Treffer:
- **Aus jeder Suche erstellbar** — Button **"🔔 Suche abonnieren"** im Ergebnis-Header
- **Einstellbares Intervall** — Stündlich / alle 6 Stunden / täglich / wöchentlich
- **E-Mail-Benachrichtigung** optional pro Alert — Throttle max. 1× pro Stunde
- **Alerts-Tab mit Badge** — Gesamtanzahl neuer Treffer über alle Alerts auf einen Blick
- **Treffer-Feed pro Alert** — Aufklappbare Liste mit "💾 Speichern" und "✕ Entfernen"
- **Synonym-Expansion serverseitig** — läuft automatisch bei jedem Alert-Durchlauf
- **CRUD** — Alerts pausieren, E-Mail togglen, löschen, "Jetzt prüfen"
- **Nutzt alle Quellen** — Adzuna + Bundesagentur für Arbeit für maximale Abdeckung

### Company-Boards (Greenhouse / Lever)
Strukturierte APIs vieler Scale-ups — schneller und zuverlässiger als Karriereseiten-Scraping:
- **Greenhouse** — z. B. Airbnb, Stripe, Shopify, GitLab, Dropbox
- **Lever** — z. B. Netflix, Figma, Eventbrite, KPMG
- **Zero-Config** — Nur Provider + Slug eingeben (z. B. `greenhouse/airbnb`)
- **Automatische Prüfung** — Einstellbares Intervall pro Board (Standard: 24h)
- **Initial-Check** sofort beim Hinzufügen
- **Sub-Tab im Karriere-Monitor** — **"📡 Company Boards"** neben "Unternehmen" und "Gefundene Stellen"
- **Treffer-Feed pro Board** — aufklappbar, mit Merkzettel-Integration
- **Neu-Badge** — Neufunde werden farblich hervorgehoben

### Karriere-Monitor
Automatische Überwachung von Unternehmens-Karriereseiten auf neue passende Stellen:
- **Seiten-Scraping** — Headless Chromium (Playwright) rendert auch JavaScript-lastige Karriereseiten
- **Keyword-Matching** — Konfigurierbare Suchbegriffe je Unternehmen (z. B. CTO, Head of IT)
- **Automatische Prüfung** — Einstellbares Prüfintervall pro Unternehmen (Standard: 24h)
- **E-Mail-Benachrichtigungen** — Sofort, täglich oder wöchentlich bei neuen Treffern (konfigurierbar im Profil)
- **Alle prüfen** — Manuell alle aktiven Watches sequenziell anstoßen mit Fortschrittsbalken
- **Sub-Tab-Ansicht** — „🏢 Unternehmen" (Verwaltung) und „🔍 Gefundene Stellen" (Job-Feed) getrennt
- **Neu-Badge** — Neufunde werden im Tab-Badge und in der Job-Liste hervorgehoben
- **CSV-Import** — Unternehmenslisten als `;`-getrennte CSV importieren (Vorlage downloadbar)
- **CRUD** — Einträge hinzufügen, bearbeiten, pausieren, alle aktivieren/deaktivieren, löschen
- **Mehrfachauswahl** — Mehrere oder alle Einträge gleichzeitig markieren und löschen
- **Globale Suchbegriffe** — Nutzerweite Keywords gelten für alle Unternehmen gleichzeitig; unternehmensspezifische Keywords kommen zusätzlich hinzu
- **Pagination** — Folgt automatisch Weiter-Links über mehrere Ergebnisseiten (max. `WATCH_MAX_PAGES`, Standard: 10)
- **Auf Merkzettel** — Gefundene Stellen per 💾-Button direkt ins Merkzettel übernehmen
- **Rate-Limiting** — Konfigurierbare Pause zwischen Scrapes (`WATCH_SCRAPE_DELAY`), korrekter Bot-User-Agent
- **Pro-Nutzer** — Jeder Benutzer verwaltet seine eigene Watchlist

### Bewerbungs-Pipeline (Kanban)
- **Drag & Drop** zwischen 5 Status-Spalten (Neu / Interessant / Beworben / Abgelehnt / Angebot)
- **Follow-up-Erinnerung** in der Karte: zeigt an, wenn eine Bewerbung 7+ Tage ohne Reaktion ist
- **Interview-Termine** setzen → **ICS-Download** für Google Calendar / Apple Calendar / Outlook
- **Anschreiben-Button** je Karte: öffnet Vorlage → Platzhalter werden gefüllt → KI-Verfeinerung optional
- **Reine Frontend-Implementierung** (HTML5 Drag & Drop, kein zusätzliches Library)

### CV-Manager & Anschreiben-Vorlagen
- **Mehrere CV-Versionen** im Profil verwalten (Markdown, eine als Standard markierbar)
- **Anschreiben-Vorlagen** mit Platzhaltern: `{{company}}`, `{{role}}`, `{{location}}`, `{{date}}`, `{{my_name}}`
- **Letter-Editor** im Pipeline-Tab: Vorlage wählen → Platzhalter werden gefüllt → bearbeiten → kopieren

### KI-Integration (optional)
Wenn `AI_API_KEY` in der `.env` gesetzt ist, stehen folgende KI-Features zur Verfügung:
- **Profil-Zusammenfassung** im Profil-Tab (Freitext: Erfahrung, Skills, Wunschposition)
- **🤖 Mit KI generieren** im Anschreiben-Editor: nutzt Profil + Job-Daten für ein vollständiges Anschreiben (Anthropic Claude)
- **Match-Score** (`/ai/match`-Endpoint): Keyword-basierte Übereinstimmung Profil ↔ Job
- **Modell konfigurierbar** via `AI_MODEL` (Standard: `claude-haiku-4-5`)
- **Graceful Degradation**: ohne API-Key bleiben nur Vorlagen + Match-Score (Keyword) verfügbar

### PWA & Web-Push
- **Installierbar** auf iOS, Android und Desktop (Add to Home Screen)
- **Service Worker** (sw.js): Cache-First für Assets, Network-First für API → funktioniert teilweise offline
- **Web-Push-Benachrichtigungen** (zusätzlich zu E-Mail) für Watch- und Alert-Treffer
- **Touch-Swipe-Gesten** in Job-Cards: → speichern, ← ignorieren
- **Mobile-optimiertes Theme** (Theme-Color, Status-Bar)
- **VAPID-Schlüssel** in `.env`: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`

### Insights & Markt-Daten
- **Salary-Insights** im Dashboard: Min-Max-Spannen + Median pro Jobtitel (aus gespeicherten Jobs mit Gehaltsangabe)
- **Skills-Heatmap**: Erkennt 40+ Tech-Skills und C-Level-Rollen in deinen gespeicherten Jobs, visualisiert nach Häufigkeit
- **Wöchentlicher Markt-Report** (Sonntags 09:00 UTC): E-Mail mit Zusammenfassung neuer Watch/Alert/Board-Treffer der letzten 7 Tage

### Datensicherung
- **Manueller Backup** — Kompletten Datenstand als JSON herunterladen (inkl. Watch-Daten)
- **Automatisches tägliches Backup** — Serverseitig um 02:00 UTC (konfigurierbar), 7 Dateien Rotation
- **Backup-Liste** — Alle serverseitigen Backups im Admin-Panel anzeigen und herunterladen
- **Wiederherstellung** — Backup-Datei hochladen und vollständig einspielen (inkl. Karriere-Monitor-Daten)

### Benutzerverwaltung
- **Registrierung & Login** — Eigenständige Konten mit Benutzername und Passwort
- **Passwort-Reset** — Per E-Mail-Link (SMTP-konfigurierbar)
- **Passwort ändern** — Im Profil-Tab mit aktuellem Passwort
- **Benachrichtigungs-Einstellungen** — E-Mail-Frequenz im Profil konfigurieren (sofort / täglich / wöchentlich)
- **Datenisolation** — Jeder Nutzer sieht nur seine eigenen gespeicherten Jobs und Jira-Konfiguration
- **Mehrbenutzer-fähig** — Beliebig viele Accounts auf einer Instanz
- **Admin-Panel** — Benutzer verwalten, sperren/entsperren, Adminrechte vergeben, Konten löschen

### Jobportal-Links (45+)
Dauerhaft über den **🌐 Portale**-Tab erreichbar — nach einer Suche zusätzlich unten in den Ergebnissen. Links werden mit den aktuellen Formularwerten (Jobtitel, Ort, Umkreis) vorausgefüllt.

| Gruppe | Portale (Auswahl) |
|---|---|
| 💻 IT & Tech | Jobvector, Heise Jobs, t3n, DEVjobs, GULP, Stack Overflow, Get in IT, Gallmond, Wellfound, Talent.io, Welcome to the Jungle |
| 👔 C-Level & Executive | Korn Ferry, Egon Zehnder, Spencer Stuart, MEYHEADHUNTER, Headgate, Kienbaum, Robert Walters, Hays Executive, Mercuri Urval, i-potentials |
| 🔍 Generelle Portale | StepStone, Indeed, LinkedIn, XING, HeyJobs, Bundesagentur für Arbeit, Interamt |

### Jira-Integration
- **Export** — Gespeicherte Jobs als Jira-Ticket anlegen (ein Klick)
- **ADF-Beschreibung** — Strukturierte Beschreibung im Atlassian Document Format
- **Custom Fields** — URL- und Unternehmens-Feld optional konfigurierbar
- **Auto-Detect** — Felder werden nach Namen automatisch erkannt
- **Feldübersicht** — Alle verfügbaren Felder des Projekts einblenden & IDs kopieren
- **Verbindungstest** — Zugangsdaten vor dem Speichern prüfen
- **CORS-Proxy** — Backend leitet Anfragen durch, damit der Browser nicht geblockt wird

---

## Voraussetzungen

- **Docker Desktop** — [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
- Eine Domain mit öffentlicher IP für automatische HTTPS-Zertifikate (Let's Encrypt via Caddy)
- Kein Node.js, kein Build-Schritt, keine weiteren Abhängigkeiten

---

## Schnellstart

```bash
# Repository klonen
git clone https://github.com/Nilshh/JobFinder.git
cd JobFinder

# Konfigurationsdatei anlegen
cp .env.example .env

# Mindestens diese Werte in .env eintragen:
#   ADZUNA_APP_ID=...
#   ADZUNA_APP_KEY=...
#   SECRET_KEY=...           # openssl rand -hex 32
#   APP_DOMAIN=ihre-domain.example.com   # Domain für HTTPS-Zertifikat (Let's Encrypt)

# Container starten
docker compose up -d

# App öffnen (nach DNS-Propagation und Zertifikatsausstellung, ~1-2 Min.)
open https://ihre-domain.example.com
```

Nach dem Start läuft:
- **`https://ihre-domain.example.com`** — JobPipeline (Caddy: Frontend + HTTPS-Proxy)
- **`http://api:5500`** (intern) — API-Backend (Flask, nur intern erreichbar)

---

## Deployment & Updates

### Komplett-Update (System + App + Rebuild)

```bash
sudo ./update.sh
```

Führt in einem Durchlauf aus: OS-Updates, Docker-Base-Image-Pull, Git Pull, DB-Backup, Container-Rebuild, Health-Check und Cleanup.

### Nur App deployen (Git Pull + Rebuild)

```bash
./deploy.sh
```

Pullt den neuesten Code, erstellt ein Backup, baut den API-Container neu und startet alle Services.

---

## Konfiguration (.env)

Vor dem ersten Start muss eine `.env`-Datei im Projektverzeichnis angelegt werden:

```bash
cp .env.example .env
```

| Variable | Beschreibung | Pflicht |
|---|---|---|
| `ADZUNA_APP_ID` | Adzuna App ID ([developer.adzuna.com](https://developer.adzuna.com/)) | ja |
| `ADZUNA_APP_KEY` | Adzuna API Key | ja |
| `SECRET_KEY` | Flask Session Secret (zufälliger String, mind. 32 Zeichen) | ja |
| `APP_DOMAIN` | Öffentliche Domain (z. B. `jobs.example.com`) — Caddy holt darüber automatisch das HTTPS-Zertifikat (Let's Encrypt) | ja |
| `ADMIN_USER` | Benutzername, der beim Start zum Admin befördert wird | Ersteinrichtung |
| `SMTP_HOST` | SMTP-Server (z. B. `smtp.gmail.com`) | E-Mail |
| `SMTP_PORT` | SMTP-Port (Standard: `587`) | E-Mail |
| `SMTP_USER` | SMTP-Benutzername / Absender-Adresse | E-Mail |
| `SMTP_PASSWORD` | SMTP-Passwort / App-Passwort | E-Mail |
| `SMTP_FROM` | Absender-Name und -Adresse | E-Mail |
| `APP_URL` | Öffentliche URL der App (z. B. `https://jobs.example.com`) | E-Mail |
| `API_CACHE_TTL` | Cache-Dauer für API-Antworten in Sekunden (Standard: `300`) | optional |
| `BACKUP_KEEP` | Anzahl aufzubewahrender automatischer Backups (Standard: `7`) | optional |
| `BACKUP_HOUR` | UTC-Stunde für das tägliche Backup (Standard: `2`, also 02:00 UTC) | optional |
| `WATCH_INTERVAL_MINUTES` | Wie oft der Scheduler fällige Watches prüft, in Minuten (Standard: `60`) | optional |
| `WATCH_SCRAPE_DELAY` | Wartezeit in Sekunden zwischen zwei aufeinanderfolgenden Scrapes (Standard: `5`) | optional |
| `WATCH_MAX_PAGES` | Maximale Seitenanzahl pro Karriereseite bei Pagination (Standard: `10`) | optional |
| `VAPID_PUBLIC_KEY` | Public Key für Web-Push-Benachrichtigungen | für Web-Push |
| `VAPID_PRIVATE_KEY` | Private Key für Web-Push-Benachrichtigungen | für Web-Push |
| `VAPID_SUBJECT` | Kontakt-URL für Web-Push (z. B. `mailto:admin@example.com`) | für Web-Push |
| `AI_API_KEY` | Anthropic API Key für KI-Anschreiben | für KI |
| `AI_MODEL` | Claude-Modell (Standard: `claude-haiku-4-5`) | optional |
| `LOG_LEVEL` | Log-Level: DEBUG / INFO / WARNING / ERROR (Standard: `INFO`) | optional |

**VAPID-Keys generieren** (für Web-Push):
```bash
pip install py-vapid
vapid --gen
```

**Anthropic API Key** (für KI-Anschreiben): unter [console.anthropic.com](https://console.anthropic.com/) erstellen.

Sicheren `SECRET_KEY` generieren:
```bash
openssl rand -hex 32
```

> **Hinweis:** SMTP-Konfiguration wird sowohl für Passwort-Reset als auch für Karriere-Monitor-Benachrichtigungen benötigt.

---

## Docker-Befehle

```bash
# Starten
docker compose up -d

# Stoppen
docker compose down

# Neu bauen (nach Änderungen an server.py oder requirements.txt)
# Änderungen an public/ (index.html, style.css, app.js) sind sofort aktiv – kein Rebuild nötig
docker compose up -d --build

# Logs anzeigen
docker compose logs -f

# Nur API-Logs
docker compose logs -f api

# Nur Caddy-Logs
docker compose logs -f caddy
```

---

## Architektur

```
Internet
  │
  └─► Caddy (HTTPS, Let's Encrypt)        ihre-domain.example.com:443
        │
        ├─► /jobs* /jira/* /auth/* /user/* /admin/* /watch/*  →  Flask API (intern :5500)
        │     │
        │     ├─► /jobs          Adzuna-Proxy (mit 5-Min-Cache)
        │     ├─► /jobs/ba       Bundesagentur-Proxy (mit 5-Min-Cache)
        │     ├─► /jobs/jobicy   Jobicy-Proxy (mit 5-Min-Cache)
        │     ├─► /jobs/remoteok RemoteOK-Proxy (mit 5-Min-Cache, nur Remote-Modus)
        │     ├─► /jobs/muse     The Muse-Proxy (mit 5-Min-Cache)
        │     ├─► /auth/*        Registrierung, Login, Logout, Passwort-Reset
        │     ├─► /user/data     Gespeicherte Jobs & Jira-Config (pro User)
        │     ├─► /user/notifications   Benachrichtigungs-Einstellungen (pro User)
        │     ├─► /admin/*       Benutzerverwaltung + Backup-Verwaltung (nur Admins)
        │     ├─► /jira/test     Verbindungstest → Jira REST API
        │     ├─► /jira/issue    Ticket erstellen → Jira REST API
        │     ├─► /jira/fields   Feldliste → Jira REST API
        │     ├─► /watch/*       Karriere-Monitor (Unternehmen, Jobs, globale Keywords)
        │     ├─► /search/alerts/*   Search-Alerts: gespeicherte Suchen (pro User)
        │     ├─► /boards/*      Company Boards: Greenhouse/Lever (pro User)
        │     ├─► /user/cvs      CV-Manager (pro User)
        │     ├─► /user/templates    Anschreiben-Vorlagen (pro User)
        │     ├─► /user/profile-summary    KI-Profil (pro User)
        │     ├─► /push/*        Web-Push: VAPID-Key, subscribe, unsubscribe
        │     ├─► /ai/match      Match-Score Profil ↔ Job
        │     ├─► /ai/coverletter   KI-Anschreiben (Anthropic)
        │     └─► /health        Health-Check (DB, Scheduler, Cache)
        │
        └─► /* (alle anderen Pfade)  →  public/ (SPA + manifest.json + sw.js)

Hintergrund-Threads:
  ├─► Tägliches Backup (02:00 UTC)
  ├─► Watch-Scheduler (prüft fällige Karriereseiten alle 60 Min.)
  ├─► Alert-Scheduler (prüft fällige Search-Alerts alle 60 Min.)
  ├─► Board-Scheduler (prüft fällige Greenhouse/Lever-Boards alle 60 Min.)
  ├─► Digest-Mailer (prüft stündlich auf ausstehende tägliche/wöchentliche E-Mails)
  └─► Weekly-Report (Sonntags 09:00 UTC)
```

### Dateien

| Datei / Verzeichnis | Beschreibung |
|---|---|
| `public/index.html` | HTML-Skelett der Single-Page-App |
| `public/style.css` | Nova Design System (Glassmorphism, CSS Custom Properties) |
| `public/app.js` | Komplette Frontend-Logik (Vanilla JS) |
| `server.py` | Flask-Backend (Auth, API-Proxies, Caching, Watch-Scheduler, Notifications) |
| `Caddyfile` | Caddy-Konfiguration (HTTPS, Reverse Proxy) |
| `Dockerfile.api` | Python-Container für das Backend |
| `docker-compose.yml` | Orchestrierung aller Services |
| `deploy.sh` | Git Pull + Backup + Docker Rebuild + Health-Check |
| `update.sh` | Komplett-Update (System + Docker + App + Rebuild) |
| `.env` | Secrets & Konfiguration (nicht im Repository) |
| `.env.example` | Vorlage für `.env` |

### Datenspeicherung

Benutzerdaten werden serverseitig in einer **SQLite-Datenbank** gespeichert (persistent via Docker Volume):

| Tabelle | Inhalt |
|---|---|
| `users` | Benutzerkonten (Passwort-Hash, E-Mail, Admin/Locked, Karriere-Monitor-Keywords, Benachrichtigungs-Einstellungen) |
| `user_data` | Gespeicherte Jobs & Jira-Konfiguration pro Benutzer |
| `password_reset_tokens` | Temporäre Reset-Tokens (1 Stunde gültig) |
| `company_watches` | Karriere-Monitor: überwachte Unternehmen pro Benutzer (URL, Keywords, Intervall, Status) |
| `watch_jobs` | Karriere-Monitor: gefundene Stellenanzeigen (Titel, URL, Neu-Flag, Zeitstempel) |
| `saved_searches` | Search-Alerts: gespeicherte Suchen pro Benutzer (Titel, Filter, Intervall, Status) |
| `alert_jobs` | Search-Alerts: gefundene Stellen pro Alert (Titel, Unternehmen, Quelle, Zeitstempel) |
| `company_boards` | Company-Boards: Greenhouse/Lever-Slugs pro Benutzer (Provider, Slug, Intervall) |
| `board_jobs` | Company-Boards: gefundene Stellen pro Board (Titel, URL, Standort, Zeitstempel) |
| `cvs` | Lebensläufe pro Benutzer (Name, Markdown-Inhalt, Standard-Flag) |
| `letter_templates` | Anschreiben-Vorlagen pro Benutzer (Name, Body mit Platzhaltern) |
| `push_subscriptions` | Web-Push-Subscriptions pro Benutzer (Endpoint, Keys) |

---

## Benutzerverwaltung

### Registrierung

1. **Anmelden**-Button oben rechts klicken
2. Auf **Registrieren** wechseln
3. Benutzername, E-Mail (optional, für Passwort-Reset und Benachrichtigungen) und Passwort eingeben

### Passwort vergessen

1. Im Login-Dialog auf **Passwort vergessen?** klicken
2. E-Mail-Adresse eingeben → Reset-Link wird zugeschickt
3. Link im E-Mail öffnen → neues Passwort setzen

> Passwort-Reset erfordert konfigurierte SMTP-Daten in der `.env`.

### Ersten Administrator einrichten

Nach der Erstinstallation gibt es noch keinen Admin-Account. So wird ein bestehender Benutzer zum Admin befördert:

1. Benutzer registrieren (falls noch nicht vorhanden)
2. In der `.env` eintragen:
   ```env
   ADMIN_USER=deinBenutzername
   ```
3. Container neu starten:
   ```bash
   docker compose up -d --build
   ```
4. Der Benutzer hat jetzt Adminrechte — **⚙️ Admin**-Button erscheint im Topbar
5. `ADMIN_USER` kann danach wieder aus der `.env` entfernt werden (Rechte bleiben erhalten)

### Admin-Panel

Erreichbar über den **⚙️ Admin**-Button (nur für Admins sichtbar):

| Funktion | Beschreibung |
|---|---|
| E-Mail anpassen | Inline editierbar, Enter oder 💾-Button |
| Sperren / Entsperren | Gesperrte Benutzer können sich nicht mehr anmelden |
| Zum Admin / Admin entziehen | Adminrechte für andere Benutzer verwalten |
| Benutzer löschen | Löscht Konto + alle gespeicherten Daten inkl. Watches (unwiderruflich) |

> Admins können sich nicht selbst sperren, ihre eigenen Adminrechte entziehen oder ihr eigenes Konto löschen.

---

## E-Mail-Benachrichtigungen

Der Karriere-Monitor kann per E-Mail über neue Stellenfunde informieren. Voraussetzung: SMTP ist in der `.env` konfiguriert.

### Einrichtung

1. Im **Profil-Tab** den Abschnitt **Benachrichtigungen** öffnen
2. E-Mail-Benachrichtigungen aktivieren
3. Häufigkeit wählen:
   - **Sofort** — E-Mail bei jedem Fund (max. 1x pro Stunde)
   - **Tägliche Zusammenfassung** — Einmal täglich alle neuen Treffer
   - **Wöchentliche Zusammenfassung** — Einmal pro Woche

> Die E-Mail enthält die gefundenen Stellentitel mit Direktlinks und einen Button zur App.

---

## Jira-Integration einrichten

### 1. API-Token erstellen

1. [id.atlassian.com → Security → API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens) öffnen
2. **Create API token** klicken, Namen vergeben, Token kopieren

### 2. Konfiguration in JobPipeline

Im **Profil-Tab** unter **Jira-Integration** ausfüllen:

| Feld | Beispiel | Pflicht |
|---|---|---|
| Jira Cloud Domain | `meinunternehmen.atlassian.net` | ja |
| E-Mail | `max@unternehmen.de` | ja |
| API Token | `ATATxxxx…` | ja |
| Projekt-Key | `JOBS` | ja |
| Issue-Typ | `Task` (Standard) | ja |
| URL-Feld | `customfield_10050` | optional |
| Unternehmen-Feld | `customfield_10051` | optional |

### 3. Verbindung testen

Auf **🔗 Testen** klicken — bei Erfolg wird der Anzeigename des Atlassian-Accounts angezeigt.

### 4. Custom Fields ermitteln

Auf **Verfügbare Felder anzeigen →** klicken:
- Alle Felder des Projekts werden geladen
- URL- und Unternehmens-Felder werden automatisch erkannt (grün markiert)
- Auf eine Field-ID klicken → kopiert sie in die Zwischenablage

---

## Troubleshooting

### Keine Suchergebnisse
- Anderen Jobtitel oder größeren Umkreis versuchen
- Ort korrekt eingegeben? (z. B. „München" statt „munich")
- `ADZUNA_APP_ID` und `ADZUNA_APP_KEY` in der `.env` prüfen

### HTTPS-Zertifikat wird nicht ausgestellt
- DNS der Domain muss auf den Server zeigen (A-Record)
- Port 80 und 443 müssen von außen erreichbar sein
- Caddy-Logs prüfen: `docker compose logs -f caddy`

### Login/Registrierung schlägt fehl
- `SECRET_KEY` in `.env` gesetzt?
- Docker-Volume `jobfinder_data` vorhanden? → `docker volume ls`

### Konto gesperrt
- Admin im **⚙️ Admin**-Panel aufrufen und Benutzer entsperren
- Kein Admin verfügbar? → `ADMIN_USER=benutzername` in `.env` + `docker compose up -d --build`

### Admin-Button nicht sichtbar
- Sicherstellen, dass `ADMIN_USER=benutzername` in `.env` gesetzt und Container neu gestartet wurde (`docker compose up -d --build`)
- Nach dem nächsten Login erscheint der Button

### E-Mail-Benachrichtigungen kommen nicht an
- SMTP-Einstellungen in `.env` prüfen (SMTP_HOST, SMTP_USER, SMTP_PASSWORD)
- E-Mail-Adresse im Profil hinterlegt?
- Spam-Ordner prüfen
- API-Logs prüfen: `docker compose logs -f api | grep Notify`

### Passwort-Reset-Mail kommt nicht an
- SMTP-Einstellungen in `.env` prüfen
- Spam-Ordner prüfen
- SMTP-Verbindung testen: `docker compose logs -f api`

### Jira: 500-Fehler / „Nicht erreichbar"
- Falsche Domain? → Domain ohne `https://` eingeben, z. B. `firma.atlassian.net`
- 500 = meist Non-JSON-Response von Jira (Redirect / falsche Domain)

### Jira: 401 Unauthorized
- API-Token prüfen (neu generieren unter id.atlassian.com)
- E-Mail-Adresse des Atlassian-Accounts verwenden (nicht LDAP/SSO)

### Jira: Custom Fields funktionieren nicht
- **Verfügbare Felder anzeigen** nutzen, um korrekte Field-IDs zu ermitteln
- Im Jira-Projekt: **Project Settings → Issue Types → Fields** → Feld zum Screen hinzufügen
- Beim ersten 400-Fehler versucht JobPipeline automatisch einen Retry ohne Custom Fields

### Ignorierliste zurücksetzen
Im Tab **📌 Merkzettel** → **🗑 Ignorierliste leeren** klicken.

---

## Lokal ohne Docker (Entwicklung)

```bash
# Abhängigkeiten installieren
pip install flask requests beautifulsoup4 playwright
playwright install chromium

# .env mit Minimalwerten anlegen
echo "ADZUNA_APP_ID=deine_id" > .env
echo "ADZUNA_APP_KEY=dein_key" >> .env
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env

# Backend starten
python server.py

# Frontend im Browser öffnen
open http://localhost:5500
```

> Ohne Docker wird keine HTTPS-Verschlüsselung genutzt. Für Production immer Docker + Caddy verwenden.

---

## Tech Stack

| Schicht | Technologie |
|---|---|
| Frontend | Vanilla HTML / CSS / JavaScript (kein Framework, kein Build) |
| Design | Nova Design System (Space Grotesk + Inter, Glassmorphism, CSS Custom Properties) |
| PWA | Service Worker (Cache + Push) · Web App Manifest |
| Backend | Python 3.12 · Flask · Requests · pywebpush |
| Datenbank | SQLite (serverseitig, Docker Volume) |
| Caching | In-Memory TTL-Cache (API-Antworten, 5 Min) |
| Authentifizierung | Session-Cookies · Werkzeug Password Hashing |
| Push | Web Push (VAPID) via pywebpush |
| E-Mail | SMTP (Benachrichtigungen + Passwort-Reset + Wochenreport) |
| Reverse Proxy / HTTPS | Caddy (automatisches Let's Encrypt) |
| Jobdaten | [Adzuna](https://developer.adzuna.com/) · [Bundesagentur](https://jobsuche.api.bund.dev/) · [Jobicy](https://jobicy.com/) · [RemoteOK](https://remoteok.com/) · [The Muse](https://www.themuse.com/developers) |
| Company-Boards | [Greenhouse](https://developers.greenhouse.io/job-board.html) · [Lever](https://github.com/lever/postings-api) |
| KI | [Anthropic Claude API](https://docs.anthropic.com/) (optional) |
| Container | Docker Compose |
| Jira | Atlassian REST API v3 · ADF |
| Karriere-Monitor | Playwright (headless Chromium) · BeautifulSoup4 |
| Tests | pytest (21 Tests, GitHub Actions CI) |
| Deployment | deploy.sh (Git Pull + Rebuild) · update.sh (System + App) |
