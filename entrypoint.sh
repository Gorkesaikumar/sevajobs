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
        if [ "$SKIP_MIGRATIONS" = "true" ] || [ "$MIGRATE_ON_STARTUP" = "false" ]; then
            echo "Skipping automatic database migrations (SKIP_MIGRATIONS=$SKIP_MIGRATIONS)."
        else
            echo "Applying database migrations..."
            python manage.py migrate --noinput
        fi

        if [ "$SKIP_COLLECTSTATIC" = "true" ]; then
            echo "Skipping static files collection (SKIP_COLLECTSTATIC=$SKIP_COLLECTSTATIC)."
        else
            echo "Collecting static files..."
            python manage.py collectstatic --noinput
        fi
        ;;
esac

export PORT=${PORT:-8000}

echo "Starting service: $*"
exec "$@"
