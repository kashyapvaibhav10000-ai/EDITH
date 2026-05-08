#!/bin/bash
LOG="/home/vaibhav/EDITH/logs/arch_updater.log"
PYTHON="/home/vaibhav/edith-env/bin/python"
SCRIPT="/home/vaibhav/EDITH/edith_arch_updater.py"

mkdir -p "$(dirname $LOG)"
echo "--- Boot: $(date) ---" >> "$LOG"

# Wait for Joplin — keep trying every 30s until success
while true; do
    sleep 30
    $PYTHON $SCRIPT >> "$LOG" 2>&1
    if grep -q "SUCCESS" "$LOG"; then
        echo "--- Success at: $(date) ---" >> "$LOG"
        break
    fi
done
