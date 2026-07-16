# Celery is imported lazily so `manage.py` works even without a broker running.
from .celery import app as celery_app

__all__ = ("celery_app",)
