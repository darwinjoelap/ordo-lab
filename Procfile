web: gunicorn config.wsgi --log-file - --workers 3 --timeout 60
release: python manage.py migrate_schemas --noinput
