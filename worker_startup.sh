#!/bin/sh

# This is the startup script for our hybrid worker container.
# It's responsible for launching both the Celery worker and the FastAPI server.

# 1. Start the Celery worker in the background.
# The '&' at the end of the line tells the shell to run this command
# as a background process. This is crucial because otherwise, the script
# would get "stuck" here and never move on to the next command.

echo "--- Starting Celery worker process in background..."
celery -A celery_app.celery_worker worker -l info -c 4 &

# 2. Start the FastAPI/Uvicorn server in the foreground.
# This will be the main process for the container.
# We bind it to port 8001 inside the container. This port must match
# what our main API service will try to call.

echo "--- Starting FastAPI/Uvicorn server for ML inference..."
uvicorn worker_api:app --host 0.0.0.0 --port 8002 --workers 1