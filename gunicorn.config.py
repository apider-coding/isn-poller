import os
import multiprocessing

port = os.environ.get('GUNICORN_BINDPORT', '8000')
bind = '0.0.0.0:' + port

# workers = int(os.environ.get('GUNICORN_PROCESSES', '1'))
workers = int(os.getenv('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2))
threads = int(os.environ.get('GUNICORN_THREADS', '1'))

forwarded_allow_ips = '*'
secure_scheme_headers = {'X-Forwarded-Proto': 'https'}
