# JobFinder — Docker Setup

## Voraussetzungen
- Docker Desktop installiert (https://www.docker.com/products/docker-desktop/)

## Starten

```bash
# 1. In den Ordner wechseln
cd jobfinder-docker

# 2. Container bauen und starten
docker compose up -d

# 3. App im Browser öffnen
open http://localhost:8080
```

## Stoppen
```bash
docker compose down
```

## Neu bauen (nach Änderungen an jobfinder.html)
```bash
docker compose up -d --build
```

## Logs anzeigen
```bash
docker compose logs -f
```
