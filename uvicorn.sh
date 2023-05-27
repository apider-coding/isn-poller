#!/bin/sh
uvicorn --host 0.0.0.0 --workers 1 app:app

# for dev
# uvicorn --reload --host 0.0.0.0 --workers 1 app:app