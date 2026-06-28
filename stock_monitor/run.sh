#!/usr/bin/env bash
# Wrapper für Cron – nutzt die virtuelle Umgebung und reicht Argumente durch.
cd "$(dirname "$0")"
exec ./.venv/bin/python stock_monitor.py "$@"
