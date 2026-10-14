"""
API-key authentication + a simple per-key rate limiter.

Each key maps to a principal and its groups (see API_KEYS_JSON in .env).
Copilot Studio sends the key in the `X-API-Key` header from its HTTP node.

Production upgrade path (mention in interviews): replace API keys with
Microsoft Entra ID OAuth tokens and read the user's groups from the token,
so each employee is filtered by their own permissions.
"""
import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from .config import settings
from .service import Principal

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _lookup(key: str):
    for known, info in settings.api_keys.items():
        if key and hmac.compare_digest(known, key):
            return Principal(
                name=info.get("principal", "unknown"),
                groups=[g.lower() for g in info.get("groups", [])],
                admin=bool(info.get("admin", False)),
            )
    return None


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, who: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[who]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


limiter = RateLimiter(settings.rate_limit_per_minute)


def require_user(key: str = Security(api_key_header)) -> Principal:
    principal = _lookup(key)
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key")
    if not limiter.allow(principal.name):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    return principal


def require_admin(principal: Principal = Depends(require_user)) -> Principal:
    if not principal.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin key required")
    return principal
