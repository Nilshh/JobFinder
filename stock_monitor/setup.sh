#!/usr/bin/env bash
# Einmaliges Setup: virtuelle Umgebung + Playwright/Chromium installieren.
set -e
cd "$(dirname "$0")"

echo "==> Virtuelle Umgebung anlegen (.venv)"
python3 -m venv .venv

echo "==> Abhängigkeiten installieren"
./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt

echo "==> Chromium für Playwright installieren"
./.venv/bin/python -m playwright install chromium

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> .env aus Vorlage erstellt – bitte TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID eintragen."
fi

echo
echo "Fertig. Nächste Schritte:"
echo "  1) .env mit Bot-Token + Chat-ID befüllen (siehe README.md)"
echo "  2) Test:   ./run.sh --test"
echo "  3) Cron einrichten (siehe README.md)"
