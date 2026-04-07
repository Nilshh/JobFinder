#!/bin/bash
# deploy.sh — Git pull + Docker rebuild + Neustart
# Verwendung: ssh server 'cd /pfad/zu/JobFinder && ./deploy.sh'
set -e

COMPOSE="docker compose"
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "──────────────────────────────────────"
echo "  JobPipeline Deploy"
echo "──────────────────────────────────────"

# 1. Git Pull
echo ""
echo "📥 Git pull..."
git fetch --all
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "✅ Bereits auf dem neuesten Stand ($LOCAL)"
    read -p "Trotzdem neu bauen? (j/N) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[jJyY]$ ]] && echo "Abgebrochen." && exit 0
fi

git pull origin main
NEW=$(git rev-parse --short HEAD)
echo "✅ Aktualisiert auf $NEW"

# 2. Backup vor Deploy
echo ""
echo "💾 Erstelle Backup vor Deploy..."
$COMPOSE exec -T api python -c "
import sys; sys.path.insert(0,'/app')
from server import _make_backup
print(_make_backup())
" 2>/dev/null && echo "✅ Backup erstellt" || echo "⚠️  Backup übersprungen (Container läuft nicht)"

# 3. Rebuild & Restart
echo ""
echo "🔨 Baue Container neu..."
$COMPOSE build --no-cache api

echo ""
echo "🚀 Starte Container neu..."
$COMPOSE up -d

# 4. Health Check
echo ""
echo "🩺 Health Check..."
sleep 3
if curl -sf http://localhost:5500/auth/me > /dev/null 2>&1; then
    echo "✅ API antwortet"
elif curl -sf http://localhost:80/ > /dev/null 2>&1; then
    echo "✅ Caddy antwortet (API startet noch...)"
else
    echo "⚠️  Keine Antwort — Logs prüfen: $COMPOSE logs api"
fi

echo ""
echo "──────────────────────────────────────"
echo "  Deploy abgeschlossen ($NEW)"
echo "  Logs:  $COMPOSE logs -f api"
echo "──────────────────────────────────────"
