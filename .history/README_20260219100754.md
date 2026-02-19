# JobPipeline

> Intelligente Jobsuche mit Bewerbungs-Tracking und Jira-Integration

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

### Merkzettel & Tracking
- **Speichern mit einem Klick** — Job landet sofort auf dem Merkzettel
- **Status-Tracking** — Neu · Interessant · Beworben · Abgelehnt · Angebot
- **Notizen** — Freies Textfeld je Stelle (Ansprechpartner, Gehaltsvorstellung, Gesprächsnotizen)
- **Status-Filter** — Merkzettel nach Bewerbungsstatus filtern
- **Persistenz** — Alles bleibt im `localStorage` erhalten (kein Account nötig)

### Jobportal-Links (33+)
Nach jeder Suche erscheinen vorausgefüllte Links zu drei Gruppen:

| Gruppe | Portale (Auswahl) |
|---|---|
| 💻 IT & Tech | Jobvector, Heise Jobs, t3n, DEVjobs, GULP, Stack Overflow, Get in IT |
| 👔 C-Level & Executive | Korn Ferry, Egon Zehnder, Spencer Stuart, MEYHEADHUNTER, Headgate, Kienbaum |
| 🔍 Generelle Portale | StepStone, Indeed, LinkedIn, XING, HeyJobs, Bundesagentur für Arbeit |

### Jira-Integration
- **Export** — Gespeicherte Jobs als Jira-Ticket anlegen (ein Klick)
- **ADF-Beschreibung** — Strukturierte Beschreibung im Atlassian Document Format
- **Custom Fields** — URL- und Unternehmens-Feld optional konfigurierbar
- **Auto-Detect** — Felder werden nach Namen automatisch erkannt
- **Feldübersicht** — Alle verfügbaren Felder des Projekts einblenden & IDs kopieren
- **Verbindungstest** — Zugangsdaten vor dem Speichern prüfen
- **Fallback** — Bei Custom-Field-Fehler automatischer Retry ohne Zusatzfelder
- **CORS-Proxy** — Backend leitet Anfragen durch, damit der Browser nicht geblockt wird

---

## Voraussetzungen

- **Docker Desktop** — [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
- Kein Node.js, kein Build-Schritt, keine weiteren Abhängigkeiten

---

## Schnellstart

```bash
# Repository klonen
git clone <repo-url>
cd jobpipeline

# Container starten (Frontend + API)
docker compose up -d

# App öffnen
open http://localhost:8080
```

Nach dem Start läuft:
- **`http://localhost:8080`** — JobPipeline Frontend (nginx)
- **`http://localhost:5500`** — API-Backend (Flask)

---

## Docker-Befehle

```bash
# Starten
docker compose up -d

# Stoppen
docker compose down

# Neu bauen (nach Änderungen an jobfinder.html oder server.py)
docker compose up -d --build

# Logs anzeigen
docker compose logs -f

# Nur API-Logs
docker compose logs -f api
```

---

## Architektur

```
Browser
  │
  ├─► jobfinder.html      Single-Page-App (HTML/CSS/JS, kein Framework)
  │     │
  │     ├─► Adzuna API    Direkte Fetch-Anfragen (CORS erlaubt)
  │     └─► localhost:5500  Flask-Proxy für Jira (CORS-Bypass)
  │
  └─► server.py           Flask-Backend
        ├─► /jobs          Adzuna-Proxy (optional)
        ├─► /jira/test     Verbindungstest → /rest/api/3/myself
        ├─► /jira/issue    Ticket erstellen → /rest/api/3/issue
        └─► /jira/fields   Feldliste → /rest/api/3/issue/createmeta/…
```

### Dateien

| Datei | Beschreibung |
|---|---|
| `jobfinder.html` | Komplette Frontend-App |
| `server.py` | Flask-Backend (Adzuna + Jira CORS-Proxy) |
| `Dockerfile` | nginx-Container für das Frontend |
| `Dockerfile.api` | Python-Container für das Backend |
| `docker-compose.yml` | Orchestrierung beider Services |

### Datenspeicherung

Alle Daten liegen ausschließlich im `localStorage` des Browsers:

| Key | Inhalt |
|---|---|
| `jf2_saved` | Gespeicherte Jobs (JSON-Objekt, Key → Job) |
| `jf2_ign` | Ignorierte Job-Keys (JSON-Array) |
| `jf2_jira` | Jira-Konfiguration |

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

### Proxy-Modus (empfohlen)

Der **Lokale Proxy**-Schalter ist standardmäßig aktiv. Er leitet alle Jira-Anfragen über `server.py`, da Browser CORS-Anfragen direkt zu Atlassian blockieren. Nur deaktivieren, wenn Jira CORS für die eigene Domain explizit erlaubt.

---

## Troubleshooting

### Keine Suchergebnisse
- Anderen Jobtitel oder größeren Umkreis versuchen
- Ort korrekt eingegeben? (z. B. „München" statt „munich")

### Jira: 500-Fehler / „Nicht erreichbar"
- Läuft Docker? → `docker compose ps`
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
# Python-Abhängigkeiten installieren
pip install flask requests

# Backend starten
python server.py

# Frontend direkt im Browser öffnen (kein Server nötig)
open jobfinder.html
```

> Die App funktioniert auch ohne Backend — die Jobsuche läuft direkt über die Adzuna-API. Nur die Jira-Integration benötigt `server.py` (CORS).

---

## Tech Stack

| Schicht | Technologie |
|---|---|
| Frontend | Vanilla HTML / CSS / JavaScript (kein Framework, kein Build) |
| Backend | Python 3.12 · Flask · Requests |
| Jobdaten | [Adzuna Jobs API](https://developer.adzuna.com/) |
| Container | Docker · nginx (Alpine) |
| Jira | Atlassian REST API v3 · ADF |
| Datenhaltung | `localStorage` (clientseitig) |
