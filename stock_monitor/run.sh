#!/usr/bin/env bash
# Wrapper für Cron – nutzt die virtuelle Umgebung und reicht Argumente durch.
# Zeitzone für Log-/Anzeige (überschreibbar via TZ in der Umgebung). So zeigen
# monitor.log und /next die lokale Zeit, auch wenn der Server auf UTC läuft.
export TZ="${TZ:-Europe/Berlin}"
cd "$(dirname "$0")"
exec ./.venv/bin/python stock_monitor.py "$@"
