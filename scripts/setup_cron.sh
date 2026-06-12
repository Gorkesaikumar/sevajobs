#!/bin/bash

# Get the absolute path of the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
BACKUP_SCRIPT="${SCRIPT_DIR}/backup.sh"

# Ensure the backup script is executable
chmod +x "${BACKUP_SCRIPT}"

# The cron expression (e.g., run every day at 2:00 AM)
CRON_SCHEDULE="0 2 * * *"

# Command to add to cron
CRON_COMMAND="${CRON_SCHEDULE} ${BACKUP_SCRIPT} >> /var/log/sevajobs_backup.log 2>&1"

# Check if cron job already exists
(crontab -l 2>/dev/null | grep -F "${BACKUP_SCRIPT}") > /dev/null

if [ $? -eq 0 ]; then
    echo "Cron job already exists for ${BACKUP_SCRIPT}."
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "${CRON_COMMAND}") | crontab -
    echo "Cron job added successfully to run at 2:00 AM daily."
fi
