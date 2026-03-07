#!/usr/bin/env bash
set -e

echo "Waiting for database..."

until python manage.py migrate --noinput; do
  echo "Database is unavailable - sleeping"
  sleep 2
done

python manage.py collectstatic --noinput

exec gunicorn ClinicHub.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -