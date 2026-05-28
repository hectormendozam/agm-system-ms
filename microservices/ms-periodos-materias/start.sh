#!/bin/sh
set -eu

until python -c "import os, psycopg2; psycopg2.connect(host=os.getenv('DB_HOST','postgres-db'), port=os.getenv('DB_PORT','5432'), dbname=os.getenv('DB_NAME','agm_periodos_materias_db'), user=os.getenv('DB_USER','postgres'), password=os.getenv('DB_PASSWORD','postgres')); print('db ready')"; do
  sleep 2
done

until python -c "import pika, os; pika.BlockingConnection(pika.URLParameters(os.getenv('RABBITMQ_URL','amqp://guest:guest@rabbitmq:5672'))).close(); print('rabbitmq ready')"; do
  sleep 2
done

python manage.py makemigrations academic
python manage.py migrate --fake-initial
python manage.py runrabbitmq &
exec python manage.py runserver 0.0.0.0:8000
