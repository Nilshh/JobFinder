#!/bin/bash
# update.sh — Komplett-Update: System, Docker, App-Code, Rebuild & Restart
# Verwendung: ssh server 'cd /pfad/zu/JobFinder && sudo ./update.sh'
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
COMPOSE="docker compose"

echo "──────────────────────────────────────"
echo "  Server Update"
echo "──────────────────────────────────────"

# Root-Check
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  Bitte mit sudo ausführen: sudo $0"
    exit 1
fi

# 1. System-Pakete aktualisieren
echo ""
echo "📦 System-Pakete aktualisieren..."
if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get upgrade -y -qq
    apt-get autoremove -y -qq
    echo "✅ APT-Pakete aktualisiert"
elif command -v dnf &>/dev/null; then
    dnf upgrade -y -q
    dnf autoremove -y -q
    echo "✅ DNF-Pakete aktualisiert"
elif command -v yum &>/dev/null; then
    yum update -y -q
    yum autoremove -y -q
    echo "✅ YUM-Pakete aktualisiert"
else
    echo "⚠️  Kein bekannter Paketmanager gefunden — übersprungen"
fi

# 2. Docker-Images aktualisieren
echo ""
echo "🐳 Docker Base-Images aktualisieren..."
docker pull python:3.12-slim
docker pull caddy:alpine
echo "✅ Base-Images aktualisiert"

# 3. Docker Cleanup
echo ""
echo "🧹 Docker Cleanup..."
BEFORE=$(docker system df --format '{{.Reclaimable}}' 2>/dev/null | head -1)
docker system prune -f --volumes=false 2>/dev/null
docker image prune -f 2>/dev/null
echo "✅ Alte Images/Container entfernt"

# 4. Git Pull
echo ""
echo "📥 Git pull..."
# Git als ursprünglicher User ausführen (nicht als root)
REAL_USER="${SUDO_USER:-$(whoami)}"
sudo -u "$REAL_USER" git fetch --all 2>/dev/null
LOCAL=$(sudo -u "$REAL_USER" git rev-parse HEAD)
REMOTE=$(sudo -u "$REAL_USER" git rev-parse origin/main)
if [ "$LOCAL" != "$REMOTE" ]; then
    sudo -u "$REAL_USER" git pull origin main
    echo "✅ Code aktualisiert auf $(sudo -u "$REAL_USER" git rev-parse --short HEAD)"
else
    echo "✅ Code bereits aktuell ($LOCAL)"
fi

# 5. Backup vor Rebuild
echo ""
echo "💾 Erstelle Backup vor Rebuild..."
$COMPOSE exec -T api python -c "
import sys; sys.path.insert(0,'/app')
from server import _make_backup
print(_make_backup())
" 2>/dev/null && echo "✅ Backup erstellt" || echo "⚠️  Backup übersprungen (Container läuft nicht)"

# 6. Container neu bauen & starten
echo ""
echo "🔨 Baue Container neu..."
$COMPOSE build --no-cache

echo ""
echo "🚀 Starte Container neu..."
$COMPOSE up -d

# 7. Docker Cleanup (nach Rebuild)
echo ""
echo "🧹 Docker Cleanup..."
docker system prune -f --volumes=false 2>/dev/null
docker image prune -f 2>/dev/null
echo "✅ Alte Images/Container entfernt"

# 8. Health Check
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

# 9. Disk-Check
echo ""
echo "💽 Speicherplatz:"
df -h / | tail -1 | awk '{print "   Belegt: "$3" / "$2" ("$5" voll)"}'

# 10. Reboot-Check
echo ""
if [ -f /var/run/reboot-required ]; then
    echo "⚠️  Neustart erforderlich (Kernel-Update)"
    read -p "   Jetzt neustarten? (j/N) " -n 1 -r
    echo
    [[ $REPLY =~ ^[jJyY]$ ]] && reboot
else
    echo "✅ Kein Neustart nötig"
fi

echo ""
echo "──────────────────────────────────────"
echo "  Komplett-Update abgeschlossen"
echo "  Logs:  $COMPOSE logs -f api"
echo "──────────────────────────────────────"
