"""Context sources for the daily planner.

Each `gather_*` function returns a short, human-readable string (or "" if the
source is not configured / unavailable). They never raise — a failing source
should not stop the whole run, so errors are caught and reported inline.
"""
from __future__ import annotations

from .calendar_source import gather_calendar
from .news_source import gather_news
from .tasks_source import gather_tasks
from .urbantrends_source import gather_urbantrends
from .weather_source import gather_weather

__all__ = [
    "gather_calendar",
    "gather_news",
    "gather_tasks",
    "gather_urbantrends",
    "gather_weather",
]
