#!/usr/bin/env bash
set -e

# انتظري DB شوي (مهم بالبداية)
python -c "import time; time.sleep(2)"

# migrations + static
python manage.py migrate --noinput
python manage.py collectstatic --noinput

# run server
gunicorn ClinicHub.wsgi:application --bind 0.0.0.0:8000 --log-file -