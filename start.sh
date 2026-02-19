#!/bin/bash
echo "📦 Installiere Abhängigkeiten..."

# Versuche pip3 / python3
if command -v pip3 &>/dev/null; then
    pip3 install flask flask-cors requests -q
elif command -v pip &>/dev/null; then
    pip install flask flask-cors requests -q
else
    echo "❌ pip nicht gefunden. Installiere Python: https://www.python.org/downloads/"
    exit 1
fi

echo "🚀 Starte JobFinder Server..."

if command -v python3 &>/dev/null; then
    python3 server.py
elif command -v python &>/dev/null; then
    python server.py
else
    echo "❌ Python nicht gefunden. Installiere Python: https://www.python.org/downloads/"
    exit 1
fi