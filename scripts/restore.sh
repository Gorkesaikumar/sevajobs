#!/bin/bash

FORCE=0
if [ "$1" == "--force" ]; then
  FORCE=1
  shift
fi

# Check if file is provided
if [ -z "$1" ]; then
  echo "Usage: ./restore.sh [--force] <path_to_backup_file.sql.gz>"
  exit 1
fi

BACKUP_FILE="$1"
DB_USER="postgres"
DB_NAME="sevajobs"
COMPOSE_FILE="docker-compose.prod.yml"

# Check if file exists
if [ ! -f "${BACKUP_FILE}" ]; then
  echo "Error: File ${BACKUP_FILE} not found!"
  exit 1
fi

if [ $FORCE -eq 0 ]; then
  echo "WARNING: This will overwrite the existing database!"
  read -p "Are you sure you want to continue? (y/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "Restore cancelled."
      exit 1
  fi
fi

echo "Restoring database from ${BACKUP_FILE}..."

# Drop all connections and restore
docker compose -f "${COMPOSE_FILE}" exec -T db psql -U ${DB_USER} -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}';"
docker compose -f "${COMPOSE_FILE}" exec -T db dropdb -U ${DB_USER} --if-exists ${DB_NAME}
docker compose -f "${COMPOSE_FILE}" exec -T db createdb -U ${DB_USER} ${DB_NAME}

# Gunzip and pipe to psql
if gunzip -c "${BACKUP_FILE}" | docker compose -f "${COMPOSE_FILE}" exec -T db psql -U ${DB_USER} -d ${DB_NAME}; then
  echo "Restore completed successfully."
else
  echo "Restore failed!"
  exit 1
fi
