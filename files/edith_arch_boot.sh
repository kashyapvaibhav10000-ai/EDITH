#!/bin/bash
# EDITH Architecture Boot Script
# Place in: /home/vaibhav/EDITH/edith_arch_boot.sh
# Runs on boot via systemd or cron

LOG="/home/vaibhav/EDITH/logs/arch_updater.log"
PYTHON="/home/vaibhav/edith-env/bin/python"
SCRIPT="/home/vaibhav/EDITH/edith_arch_updater.py"

mkdir -p "$(dirname $LOG)"

echo "--- Boot run: $(date) ---" >> "$LOG"

# Wait for desktop session to be ready (Joplin needs GUI)
sleep 30

# Run updater
$PYTHON $SCRIPT >> "$LOG" 2>&1

echo "--- Done: $(date) ---" >> "$LOG"
