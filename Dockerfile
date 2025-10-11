FROM python:3.11-slim-buster

ENV BINDPORT=8000

RUN cp -r -f /usr/share/zoneinfo/Europe/Stockholm /etc/localtime

ADD . /app

WORKDIR /app

RUN pip3 --no-cache install -r requirements.txt

RUN rm -rf Dockerfile* requirements* .gitignore .git .vscode __pycache__ dconfig.json manifest*

ENV PYTHONUNBUFFERED=1

EXPOSE $BINDPORT/tcp

# Run gunicorn
# ENTRYPOINT ["/app/gunicorn.sh"]
ENTRYPOINT ["/app/uvicorn.sh"]

# ENTRYPOINT ["python3"]
# CMD ["app.py"]
# CMD ["uvicorn", "--host", "0.0.0.0", "app:app"]