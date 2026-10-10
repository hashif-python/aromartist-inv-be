#!/bin/sh
set -eu
python - <<'PY'
import os,time
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.development')
import django
django.setup()
from django.db import connection
for attempt in range(60):
    try:
        connection.ensure_connection()
        break
    except Exception:
        if attempt==59: raise
        time.sleep(1)
PY
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec "$@"
