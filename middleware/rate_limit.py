import time
import asyncio
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_rate_limit_cache = {}
_rate_limit_lock = asyncio.Lock()
_RATE_LIMIT_MAX = 120
_RATE_LIMIT_WINDOW = 60


class rate_limit_middleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()

        async with _rate_limit_lock:
            stale_keys = [k for k, (_, ts) in _rate_limit_cache.items() if now - ts > 86400]
            for k in stale_keys:
                del _rate_limit_cache[k]

            if ip in _rate_limit_cache:
                count, start_time = _rate_limit_cache[ip]
                if now - start_time > _RATE_LIMIT_WINDOW:
                    _rate_limit_cache[ip] = (1, now)
                else:
                    if count >= _RATE_LIMIT_MAX:
                        return JSONResponse(status_code=429, content={"error": "Rate limit exceeded. Too many requests."})
                    _rate_limit_cache[ip] = (count + 1, start_time)
            else:
                _rate_limit_cache[ip] = (1, now)

        return await call_next(request)
