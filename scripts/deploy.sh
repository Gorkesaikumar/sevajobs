#!/bin/bash
set -e

# Change to the repository root directory safely
cd "$(dirname "$0")/.."

# Configuration
COMPOSE_FILE="docker-compose.prod.yml"
ROLLBACK_SCRIPT="./scripts/rollback.sh"
BACKUP_SCRIPT="./scripts/backup.sh"

echo "======================================"
echo "Starting Deployment Pipeline"
echo "======================================"

# 1. Save current git state for potential rollback
PREVIOUS_COMMIT=$(git rev-parse HEAD)
echo "Current commit: ${PREVIOUS_COMMIT}"

# 2. Backup database before deployment
echo "Taking database backup..."
if [ -x "${BACKUP_SCRIPT}" ]; then
  # Execute backup and capture the exact filename printed on stdout
  BACKUP_FILE=$(${BACKUP_SCRIPT} | tail -n 1)
  if [ -z "${BACKUP_FILE}" ] || [ ! -f "${BACKUP_FILE}" ]; then
    echo "ERROR: Backup failed or file not found. Aborting deployment."
    exit 1
  fi
  echo "Backup successfully created: ${BACKUP_FILE}"
else
  echo "ERROR: Backup script not found or not executable. Aborting deployment."
  exit 1
fi

# 3. Pull latest code
echo "Pulling latest code from git..."
git pull origin main || { echo "Git pull failed!"; exit 1; }

NEW_COMMIT=$(git rev-parse HEAD)
if [ "${PREVIOUS_COMMIT}" == "${NEW_COMMIT}" ]; then
  echo "No new changes to deploy. Skipping."
  exit 0
fi

# 4. Build and start containers
echo "Building and restarting Docker containers..."
if ! docker compose -f ${COMPOSE_FILE} build; then
  echo "ERROR: Docker build failed! Triggering rollback..."
  ${ROLLBACK_SCRIPT} "${PREVIOUS_COMMIT}" "${BACKUP_FILE}"
  exit 1
fi

if ! docker compose -f ${COMPOSE_FILE} up -d; then
  echo "ERROR: Docker compose up failed! Triggering rollback..."
  ${ROLLBACK_SCRIPT} "${PREVIOUS_COMMIT}" "${BACKUP_FILE}"
  exit 1
fi

# Note: Entrypoint.sh handles automatic migrations and collectstatic.
# We verify their success by checking the health endpoints.

# 5. Verify Health Checks
echo "Waiting for services to become healthy..."
MAX_RETRIES=12  # Wait up to 60 seconds (12 * 5s)
RETRY_COUNT=0
HEALTHY=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  sleep 5
  
  # Check if any container is in unhealthy state
  UNHEALTHY_CONTAINERS=$(docker compose -f ${COMPOSE_FILE} ps -q | xargs -r docker inspect -f '{{.State.Health.Status}}' | grep "unhealthy" || true)
  
  if [ -n "$UNHEALTHY_CONTAINERS" ]; then
    echo "ERROR: One or more containers are unhealthy! Triggering rollback..."
    ${ROLLBACK_SCRIPT} "${PREVIOUS_COMMIT}" "${BACKUP_FILE}"
    exit 1
  fi

  # Check if all containers are healthy
  TOTAL_CONTAINERS=$(docker compose -f ${COMPOSE_FILE} ps -q | wc -l)
  HEALTHY_CONTAINERS=$(docker compose -f ${COMPOSE_FILE} ps -q | xargs -r docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}healthy{{end}}' | grep "^healthy$" | wc -l || echo 0)

  if [ "$TOTAL_CONTAINERS" -eq "$HEALTHY_CONTAINERS" ] && [ "$TOTAL_CONTAINERS" -gt 0 ]; then
    HEALTHY=true
    break
  fi

  echo "Waiting... ($HEALTHY_CONTAINERS/$TOTAL_CONTAINERS healthy)"
  RETRY_COUNT=$((RETRY_COUNT+1))
done

if [ "$HEALTHY" = true ]; then
  echo "======================================"
  echo "Deployment successful! All services are healthy."
  echo "======================================"
else
  echo "ERROR: Health checks timed out! Triggering rollback..."
  ${ROLLBACK_SCRIPT} "${PREVIOUS_COMMIT}" "${BACKUP_FILE}"
  exit 1
fi
