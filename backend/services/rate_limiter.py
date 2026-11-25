"""
Rate Limiter Service
--------------------
Asynchronous sliding-window request rate limiter and quota cooldown coordinator.
Prevents HTTP 429 RESOURCE_EXHAUSTED errors when calling rate-limited LLM providers
(e.g., Google Gemini Free-Tier limit of 5 requests per minute).

Guarantees:
- Strict sliding-window pacing (configurable requests per minute, default 4).
- Concurrency-safe via asyncio.Lock.
- Honors upstream RetryInfo delays with safety buffer.
- Global cooldown prevents concurrent chunks from hammering an exhausted quota.
- Non-blocking asynchronous sleeps keep FastAPI and Streamlit responsive.
"""

from backend.services.inspection_progress import report
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from backend.config import settings

logger = logging.getLogger(__name__)


class RequestRateLimiter:
    """
    Asynchronous, sliding-window rate limiter with global quota cooldown.
    """

    def __init__(
        self,
        requests_per_minute: Optional[int] = None,
        safety_buffer: Optional[float] = None,
        min_interval_seconds: float = 1.0,
    ):
        """
        Args:
            requests_per_minute: Maximum requests allowed in a rolling 60-second window.
                                 Defaults to settings.LLM_REQUESTS_PER_MINUTE (default 4).
            safety_buffer: Additional seconds to wait beyond provider's RetryInfo delay.
                           Defaults to settings.LLM_RATE_LIMIT_SAFETY_BUFFER (default 2.0).
            min_interval_seconds: Minimum delay between consecutive requests to avoid burst spikes.
        """
        self.requests_per_minute = requests_per_minute or getattr(settings, "LLM_REQUESTS_PER_MINUTE", 4)
        self.safety_buffer = safety_buffer or getattr(settings, "LLM_RATE_LIMIT_SAFETY_BUFFER", 2.0)
        self.min_interval_seconds = min_interval_seconds

        self._timestamps: List[float] = []
        self._cooldown_until: float = 0.0
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def notify_quota_exhausted(self, retry_delay: float) -> float:
        """
        Notifies the rate limiter that an HTTP 429 was encountered.
        Sets a global cooldown so no other chunk or request fires until the quota resets.

        Args:
            retry_delay: Delay requested by upstream provider in seconds.

        Returns:
            The total cooldown duration including safety buffer.
        """
        total_cooldown = max(1.0, float(retry_delay)) + self.safety_buffer
        target_time = time.monotonic() + total_cooldown
        if target_time > self._cooldown_until:
            self._cooldown_until = target_time
            logger.warning(
                f"RateLimiter: Quota exhausted. Cooldown set for {total_cooldown:.1f}s "
                f"before requests resume."
            )
        return total_cooldown

    def is_in_cooldown(self) -> bool:
        """Returns True if the rate limiter is currently in a quota cooldown."""
        return time.monotonic() < self._cooldown_until

    def get_cooldown_remaining(self) -> float:
        """Returns remaining cooldown seconds, or 0.0 if not in cooldown."""
        remaining = self._cooldown_until - time.monotonic()
        return max(0.0, remaining)

    def get_status(self) -> Dict[str, Any]:
        """Returns current operational diagnostics of the rate limiter."""
        now = time.monotonic()
        active_window = [t for t in self._timestamps if now - t < 60.0]
        return {
            "requests_last_minute": len(active_window),
            "max_requests_per_minute": self.requests_per_minute,
            "in_cooldown": self.is_in_cooldown(),
            "cooldown_remaining_seconds": round(self.get_cooldown_remaining(), 1),
        }

    def reset(self) -> None:
        """Resets all sliding timestamps and cooldowns. Useful for testing."""
        self._timestamps.clear()
        self._cooldown_until = 0.0

    async def acquire(self) -> float:
        """
        Acquires permission to execute a single LLM API request.
        Asynchronously waits if in cooldown, if the rolling window is saturated,
        or if consecutive requests are too close together.

        Returns:
            The total time in seconds spent waiting, if any.
        """
        total_waited = 0.0
        lock = self._get_lock()

        async with lock:
            while True:
                now = time.monotonic()
                remaining = self._cooldown_until - now
                if remaining > 0:
                    report("WAITING_FOR_QUOTA", delay=remaining)
                    await asyncio.sleep(remaining)
                    report("ANALYZING")
                    total_waited += remaining
                    continue
                # Prune timestamps older than 60 seconds
                self._timestamps = [t for t in self._timestamps if now - t < 60.0]

                if len(self._timestamps) < self.requests_per_minute:
                    # Slot available; check minimum spacing from most recent call
                    if self._timestamps:
                        elapsed_since_last = now - self._timestamps[-1]
                        if elapsed_since_last < self.min_interval_seconds:
                            spacing_wait = self.min_interval_seconds - elapsed_since_last
                            report("WAITING_FOR_QUOTA", delay=spacing_wait)
                            await asyncio.sleep(spacing_wait)
                            report("ANALYZING")
                            total_waited += spacing_wait
                            continue

                    # Record this request
                    self._timestamps.append(now)
                    return total_waited

                # Rolling window is full. Calculate sleep time until the oldest slot expires.
                oldest = self._timestamps[0]
                sleep_needed = (oldest + 60.0) - now + 0.1
                if sleep_needed > 0:
                    logger.info(
                        f"RateLimiter: Rolling window full ({len(self._timestamps)}/{self.requests_per_minute}). "
                        f"Pacing request: sleeping {sleep_needed:.2f}s..."
                    )
                    report("WAITING_FOR_QUOTA", delay=sleep_needed)
                    await asyncio.sleep(sleep_needed)
                    report("ANALYZING")
                    total_waited += sleep_needed


# Global rate limiter singleton
request_rate_limiter = RequestRateLimiter()

