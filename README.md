# JobPipeline

> Intelligente Jobsuche mit Bewerbungs-Tracking, Jira-Integration und Mehrbenutzer-Unterstützung

JobPipeline ist eine schlanke Single-Page-App für die strukturierte Jobsuche. Sie durchsucht die **Adzuna-API** parallel nach mehreren Jobtiteln, filtert bereits gespeicherte oder ignorierte Stellen automatisch heraus und verlinkt direkt auf **33+ Jobportale**. Gespeicherte Stellen lassen sich mit Status und Notizen tracken und per Knopfdruck als Jira-Ticket exportieren.

---

## Features

### Jobsuche
- **Mehrfach-Titelsuche** — Vordefinierte Chips (CTO, CIO, CDO, Head of IT, Leiter IT u. a.) + eigene Titel
- **Parallele Suche** — Alle gewählten Jobtitel werden gleichzeitig abgefragt
- **Standort-Filter** — Ort, PLZ und Umkreis (10 / 25 / 50 / 100 / 150 km)
- **Zeitfilter** — Letzte Woche / 2 Wochen / Monat / alle
- **DACH-Support** — Automatische Länder-Erkennung (DE / AT / CH)
- **Deduplication** — Bereits gespeicherte oder ignorierte Stellen werden ausgeblendet
- **Ignorier-Funktion** — Stellen einmalig wegklicken, tauchen bei nächster Suche nicht mehr auf
- **Ohne Anmeldung nutzbar** — Die Suche funktioniert auch ohne Account

### Merkzettel & Tracking
- **Speichern mit einem Klick** — Job landet sofort auf dem Merkzettel
- **Status-Tracking** — Neu · Interessant · Beworben · Abgelehnt · Angebot
- **Notizen** — Freies Textfeld je Stelle (Ansprechpartner, Gehaltsvorstellung, Gesprächsnotizen)
- **Status-Filter** — Merkzettel nach Bewerbungsstatus filtern
- **Serverseitige Persistenz** — Daten werden pro Benutzer in SQLite gespeichert

### Benutzerverwaltung
- **Registrierung & Login** — Eigenständige Konten mit Benutzername und Passwort
- **Passwort-Reset** — Per E-Mail-Link (SMTP-konfigurierbar)
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
# .env mit echten Werten befüllen (siehe Abschnitt "Konfiguration")

# Container starten
docker compose up -d

# App öffnen (nach DNS-Propagation und Zertifikatsausstellung)
open https://job.raddes.de
```

Nach dem Start läuft:
- **`https://job.raddes.de`** — JobPipeline (Caddy: Frontend + HTTPS-Proxy)
- **`http://api:5500`** (intern) — API-Backend (Flask, nur intern erreichbar)

---

## Konfiguration (.env)

Vor dem ersten Start muss eine `.env`-Datei im Projektverzeichnis angelegt werden:

```bash
cp .env.example .env
```

| Variable | Beschreibung | Pflicht |
|---|---|---|
| `ADZUNA_APP_ID` | Adzuna App ID ([developer.adzuna.com](https://developer.adzuna.com/)) | ✅ |
| `ADZUNA_APP_KEY` | Adzuna API Key | ✅ |
| `SECRET_KEY` | Flask Session Secret (zufälliger String, mind. 32 Zeichen) | ✅ |
| `ADMIN_USER` | Benutzername, der beim Start zum Admin befördert wird | Ersteinrichtung |
| `SMTP_HOST` | SMTP-Server (z. B. `smtp.gmail.com`) | für Passwort-Reset |
| `SMTP_PORT` | SMTP-Port (Standard: `587`) | für Passwort-Reset |
| `SMTP_USER` | SMTP-Benutzername / Absender-Adresse | für Passwort-Reset |
| `SMTP_PASSWORD` | SMTP-Passwort / App-Passwort | für Passwort-Reset |
| `SMTP_FROM` | Absender-Name und -Adresse | für Passwort-Reset |
| `APP_URL` | Öffentliche URL der App (z. B. `https://job.raddes.de`) | für Passwort-Reset |

Sicheren `SECRET_KEY` generieren:
```bash
openssl rand -hex 32
```

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
  └─► Caddy (HTTPS, Let's Encrypt)        job.raddes.de:443
        │
        ├─► /jobs /jira/* /auth/* /user/* /admin/*  →  Flask API (intern :5500)
        │     │
        │     ├─► /jobs          Adzuna-Proxy (API Key bleibt serverseitig)
        │     ├─► /auth/*        Registrierung, Login, Logout, Passwort-Reset
        │     ├─► /user/data     Gespeicherte Jobs & Jira-Config (pro User)
        │     ├─► /admin/users   Benutzerverwaltung (nur Admins)
        │     ├─► /jira/test     Verbindungstest → Jira REST API
        │     ├─► /jira/issue    Ticket erstellen → Jira REST API
        │     └─► /jira/fields   Feldliste → Jira REST API
        │
        └─► /* (alle anderen Pfade)  →  public/ (statische SPA: index.html, style.css, app.js)
```

### Dateien

| Datei / Verzeichnis | Beschreibung |
|---|---|
| `public/index.html` | HTML-Skelett der Single-Page-App |
| `public/style.css` | Alle CSS-Regeln |
| `public/app.js` | Komplette Frontend-Logik (Vanilla JS) |
| `server.py` | Flask-Backend (Auth, Adzuna-Proxy, Jira-Proxy, SQLite) |
| `Caddyfile` | Caddy-Konfiguration (HTTPS, Reverse Proxy) |
| `Dockerfile.api` | Python-Container für das Backend |
| `docker-compose.yml` | Orchestrierung aller Services |
| `.env` | Secrets & Konfiguration (nicht im Repository) |
| `.env.example` | Vorlage für `.env` |
| `.gitignore` | Schützt `.env` und Datenbankdateien vor Commits |

### Datenspeicherung

Benutzerdaten werden serverseitig in einer **SQLite-Datenbank** gespeichert (persistent via Docker Volume):

| Tabelle | Inhalt |
|---|---|
| `users` | Benutzerkonten (Benutzername, Passwort-Hash, E-Mail, is_admin, is_locked) |
| `user_data` | Gespeicherte Jobs & Jira-Konfiguration pro Benutzer |
| `password_reset_tokens` | Temporäre Reset-Tokens (1 Stunde gültig) |

---

## Benutzerverwaltung

### Registrierung

1. **Anmelden**-Button oben rechts klicken
2. Auf **Registrieren** wechseln
3. Benutzername, E-Mail (optional, für Passwort-Reset) und Passwort eingeben

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
| Benutzer löschen | Löscht Konto + alle gespeicherten Daten (unwiderruflich) |

> Admins können sich nicht selbst sperren, ihre eigenen Adminrechte entziehen oder ihr eigenes Konto löschen.

---

## Jira-Integration einrichten

### 1. API-Token erstellen

1. [id.atlassian.com → Security → API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens) öffnen
2. **Create API token** klicken, Namen vergeben, Token kopieren

### 2. Konfiguration in JobPipeline

⚡ **Jira**-Button oben rechts klicken und ausfüllen:

| Feld | Beispiel | Pflicht |
|---|---|---|
| Jira Cloud Domain | `meinunternehmen.atlassian.net` | ✅ |
| E-Mail | `max@unternehmen.de` | ✅ |
| API Token | `ATATxxxx…` | ✅ |
| Projekt-Key | `JOBS` | ✅ |
| Issue-Typ | `Task` (Standard) | ✅ |
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
pip install flask requests

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
| Backend | Python 3.12 · Flask · Requests |
| Datenbank | SQLite (serverseitig, Docker Volume) |
| Authentifizierung | Session-Cookies · Werkzeug Password Hashing |
| Reverse Proxy / HTTPS | Caddy (automatisches Let's Encrypt) |
| Jobdaten | [Adzuna Jobs API](https://developer.adzuna.com/) |
| Container | Docker Compose |
| Jira | Atlassian REST API v3 · ADF |
