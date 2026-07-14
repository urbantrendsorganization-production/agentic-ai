"""Celery application for async tool calls (used from P2/P6 onward).

In local dev and tests CELERY_TASK_ALWAYS_EAGER keeps everything synchronous,
so no broker is required for the P1 loop to run.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("mica")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
