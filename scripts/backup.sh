#!/bin/bash
set -e

# Configuration
BACKUP_DIR="/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/db_backup_${TIMESTAMP}.sql.gz"
DB_USER="postgres"
DB_NAME="sevajobs"
COMPOSE_FILE="docker-compose.prod.yml"

# Ensure backup directory exists
mkdir -p "${BACKUP_DIR}"

echo "Starting database backup..." >&2

# Run pg_dump inside the postgres container via docker compose and gzip the output
if docker compose -f "${COMPOSE_FILE}" exec -T db pg_dump -U ${DB_USER} ${DB_NAME} | gzip > "${BACKUP_FILE}"; then
  echo "Backup successful: ${BACKUP_FILE}" >&2
  
  # Print only the backup file path to stdout for other scripts to capture
  echo "${BACKUP_FILE}"
  
  # Keep only the last 7 backups
  find ${BACKUP_DIR} -name "db_backup_*.sql.gz" -type f -mtime +7 -delete
else
  echo "Backup failed!" >&2
  rm -f "${BACKUP_FILE}"
  exit 1
fi
