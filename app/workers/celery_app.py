"""
Celery application configuration for DiffMaster.

Connects to Redis broker for async task queue.
Workers are started with: celery -A app.workers.celery_app worker --loglevel=info
"""

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "diffmaster",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.review_tasks"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task execution limits
    task_soft_time_limit=300,    # 5 min: raises SoftTimeLimitExceeded
    task_time_limit=600,         # 10 min: hard kill

    # Retry configuration
    task_max_retries=3,
    task_default_retry_delay=30,

    # Worker behavior
    worker_prefetch_multiplier=1,   # One task at a time per worker (memory safety)
    task_acks_late=True,            # Ack after completion (safe retry on crash)

    # Result expiry
    result_expires=86400,           # Keep results for 1 day
)
