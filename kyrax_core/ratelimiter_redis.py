# kyrax_core/ratelimiter_redis.py
"""
Redis-backed sliding window rate limiter with in-memory fallback.

Usage:
    from kyrax_core.ratelimiter_redis import get_rate_limiter
    rl = get_rate_limiter(window_sec=60, max_requests=20)
    ok, msg = rl.check(user_id)
"""

import time
import threading
import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# Try redis-py
try:
    import redis
except Exception:
    redis = None

from kyrax_core.config import REDIS_URL

class InMemoryRateLimiter:
    def __init__(self, window_sec: int = 60, max_requests: int = 20):
        self.window = window_sec
        self.max = max_requests
        self._store = {}
        self._lock = threading.Lock()

    def check(self, user_id: str) -> Tuple[bool, Optional[str]]:
        now = time.time()
        with self._lock:
            lst = self._store.setdefault(user_id, [])
            cutoff = now - self.window
            while lst and lst[0] < cutoff:
                lst.pop(0)
            if len(lst) >= self.max:
                return False, f"rate_limit_exceeded: {len(lst)}/{self.max} in {self.window}s"
            lst.append(now)
            return True, None

class RedisRateLimiter:
    """
    Simple sliding window using sorted set timestamps per user.
    Keys: "kyrax:rl:{user_id}"
    """
    def __init__(self, redis_url: str = REDIS_URL, window_sec: int = 60, max_requests: int = 20):
        if redis is None:
            raise RuntimeError("redis library not installed")
        self.client = redis.from_url(redis_url, decode_responses=True)
        self.window = int(window_sec)
        self.max = int(max_requests)

    def check(self, user_id: str) -> Tuple[bool, Optional[str]]:
        now = int(time.time() * 1000)
        key = f"kyrax:rl:{user_id}"
        with self.client.pipeline() as pipe:
            cutoff = now - (self.window * 1000)
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            pipe.execute()
        # add and check count atomically
        with self.client.pipeline() as pipe:
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, self.window + 5)
            res = pipe.execute()
        count = int(res[1])
        if count > self.max:
            return False, f"rate_limit_exceeded: {count}/{self.max} in {self.window}s"
        return True, None

def get_rate_limiter(window_sec: int = 60, max_requests: int = 20):
    # Prefer Redis if available and reachable, otherwise fallback
    if redis is not None:
        try:
            rl = RedisRateLimiter(window_sec=window_sec, max_requests=max_requests)
            # try a ping
            rl.client.ping()
            return rl
        except Exception as e:
            log.warning("RedisRateLimiter unavailable (%s) — falling back to in-memory", e)
    return InMemoryRateLimiter(window_sec=window_sec, max_requests=max_requests)
