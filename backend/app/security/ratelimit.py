"""Per-session sliding-window rate limit (SYS-002)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from ..config import rule_param


class RateLimiter:
    def __init__(self, max_requests: int | None = None, window_seconds: float | None = None):
        self.max_requests = int(max_requests or rule_param("SYS-002", "max_requests", 30))
        self.window = float(window_seconds or rule_param("SYS-002", "window_seconds", 60))
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """Record a request; return False if the key is over the limit."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_requests:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
