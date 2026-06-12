#!/bin/bash
set -e

# Change to the repository root directory safely
cd "$(dirname "$0")/.."

if [ "$#" -ne 2 ]; then
  echo "Usage: ./rollback.sh <git_commit_hash> <path_to_backup_file>"
  exit 1
fi

PREVIOUS_COMMIT="$1"
BACKUP_FILE="$2"
COMPOSE_FILE="docker-compose.prod.yml"
RESTORE_SCRIPT="./scripts/restore.sh"

echo "======================================"
echo "INITIATING EMERGENCY ROLLBACK"
echo "======================================"

echo "1. Reverting code to commit: ${PREVIOUS_COMMIT}"
git reset --hard "${PREVIOUS_COMMIT}"

echo "2. Rebuilding containers with previous code..."
docker compose -f ${COMPOSE_FILE} build

echo "3. Starting infrastructure (ignoring temporary application crashes)..."
# Start containers. The web app might crash momentarily if DB schema is out of sync,
# but the database container will stay up.
docker compose -f ${COMPOSE_FILE} up -d

echo "4. Restoring database to previous state..."
if [ -x "${RESTORE_SCRIPT}" ]; then
  ${RESTORE_SCRIPT} --force "${BACKUP_FILE}"
else
  echo "CRITICAL ERROR: Restore script not found or executable! Manual intervention required."
  exit 1
fi

echo "5. Restarting application services..."
docker compose -f ${COMPOSE_FILE} restart web celery_worker celery_beat

echo "======================================"
echo "Rollback completed. Please monitor the logs."
echo "======================================"
