"""In-memory abuse protection for the public /query endpoint (per-client sliding window + a global daily cap).

State lives in the process, so it resets on restart and is per-instance: fine for a single-container deployment.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable


class RateLimitExceeded(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self, per_hour: int = 0, daily_cap: int = 0, clock: Callable[[], float] = time.time):
        self._per_hour, self._daily_cap, self._clock = per_hour, daily_cap, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._day_start, self._day_count = clock(), 0
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._per_hour > 0 or self._daily_cap > 0

    def check(self, client: str) -> None:
        """Record one request for ``client`` or raise RateLimitExceeded. Rejected requests are not counted."""
        if not self.enabled:
            return
        now = self._clock()
        with self._lock:
            if now - self._day_start >= 86400:
                self._day_start, self._day_count = now, 0
            if self._daily_cap and self._day_count >= self._daily_cap:
                raise RateLimitExceeded("The service has reached its daily question limit. Please try again tomorrow.",
                                        int(self._day_start + 86400 - now) + 1)
            if self._per_hour:
                q = self._hits[client]
                while q and now - q[0] >= 3600:
                    q.popleft()
                if len(q) >= self._per_hour:
                    raise RateLimitExceeded(f"Too many questions from your network (limit {self._per_hour} per hour). Please wait a bit.",
                                            int(q[0] + 3600 - now) + 1)
                q.append(now)
                if len(self._hits) > 10_000:  # bound memory: drop idle clients
                    for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= 3600]:
                        del self._hits[k]
            self._day_count += 1


def client_ip(forwarded_for: str | None, peer: str | None, hops: int) -> str:
    """Client address behind ``hops`` trusted proxies: the Nth entry from the RIGHT of X-Forwarded-For
    (earlier entries are client-controlled and spoofable). With no proxy (hops=0) use the socket peer."""
    if hops > 0 and forwarded_for:
        parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return peer or "unknown"
