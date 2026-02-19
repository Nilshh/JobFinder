#!/bin/bash
# Entwicklungs-Startskript (ohne Docker)
# Für Production: docker compose up -d --build
echo "📦 Installiere Abhängigkeiten..."

# Versuche pip3 / python3
if command -v pip3 &>/dev/null; then
    pip3 install flask requests -q
elif command -v pip &>/dev/null; then
    pip install flask requests -q
else
    echo "❌ pip nicht gefunden. Installiere Python: https://www.python.org/downloads/"
    exit 1
fi

echo "🚀 Starte JobPipeline API-Server..."
echo "   Hinweis: .env Datei mit ADZUNA_APP_ID, ADZUNA_APP_KEY und SECRET_KEY muss vorhanden sein."

if command -v python3 &>/dev/null; then
    python3 server.py
elif command -v python &>/dev/null; then
    python server.py
else
    echo "❌ Python nicht gefunden. Installiere Python: https://www.python.org/downloads/"
    exit 1
fi