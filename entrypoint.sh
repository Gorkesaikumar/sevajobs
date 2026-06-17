#!/bin/sh

set -e

echo "Waiting for PostgreSQL to start..."
while ! pg_isready -h ${DB_HOST:-db} -U ${DB_USER:-postgres} -q; do
  sleep 1
done
echo "PostgreSQL started"

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Starting Gunicorn..."
# If PORT is not set, default to 8000
export PORT=${PORT:-8000}

# Execute the CMD from Dockerfile or docker-compose
exec "$@"
