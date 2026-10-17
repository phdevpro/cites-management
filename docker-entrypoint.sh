#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py load_initial_data --if-empty
exec "$@"
