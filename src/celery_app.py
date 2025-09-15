from celery import Celery
from config import settings

# Create a Celery instance
# The first argument is the name of the current module.
# The 'broker' and 'backend' are specified for where to send/receive messages.
celery_worker = Celery(
    "lexi_graph_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    # include=["tasks"] # List of modules to import when the worker starts.
)

celery_worker.conf.update(
    task_track_started=True,
    imports=("tasks",),
)