#!/bin/sh
# app:app - first is app.py : second is Flask instance name
gunicorn --chdir /app app:app -c gunicorn.config.py

# SSL
#gunicorn --chdir /app --certfile=/app/certs/server-cert.pem --keyfile=/app/certs/server-key.pem app:app -c gunicorn.config.py

# or
# gunicorn -c gunicorn.config.py project.wsgi

# SSL
# gunicorn --certfile=server.crt --keyfile=server.key --bind 0.0.0.0:443 test:app