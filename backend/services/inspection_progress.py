"""Per-task progress notifications for inspection and provider operations."""
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

observer = ContextVar("inspection_observer", default=None)
cache_hit = ContextVar("inspection_cache_hit", default=False)


def report(stage, outcome=None, delay=None):
    callback = observer.get()
    if callback is not None:
        retry_at = None if delay is None else (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        callback(stage, outcome, retry_at)
