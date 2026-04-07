#!/bin/bash
# update.sh — System-Updates für den Server (OS, Docker, Cleanup)
# Verwendung: ssh server 'sudo ./update.sh'
set -e

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

# 4. Disk-Check
echo ""
echo "💽 Speicherplatz:"
df -h / | tail -1 | awk '{print "   Belegt: "$3" / "$2" ("$5" voll)"}'

# 5. Reboot-Check
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
echo "  Server-Update abgeschlossen"
echo "  Nächster Schritt: ./deploy.sh"
echo "──────────────────────────────────────"
