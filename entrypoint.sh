#!/bin/sh

set -e

echo "Waiting for PostgreSQL to start..."
while ! pg_isready -h ${DB_HOST:-db} -U ${DB_USER:-postgres} -q; do
    sleep 1
done
echo "PostgreSQL started"

case "$*" in
    *celery*)
        echo "Celery service detected - skipping migrations and collectstatic."
        ;;
    *)
        echo "Applying database migrations..."
        python manage.py migrate --noinput

        echo "Collecting static files..."
        python manage.py collectstatic --noinput
        ;;
esac

export PORT=${PORT:-8000}

echo "Starting service: $*"
exec "$@"
