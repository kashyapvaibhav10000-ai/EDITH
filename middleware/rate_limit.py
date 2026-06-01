import time
import asyncio
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_rate_limit_cache = {}
_rate_limit_lock = asyncio.Lock()
_RATE_LIMIT_CHAT = 20     # /api/chat and /api/chat/stream — LLM calls, expensive
_RATE_LIMIT_DEFAULT = 60  # all other endpoints
_RATE_LIMIT_WINDOW = 60

_CHAT_PATHS = {"/api/chat", "/api/chat/stream"}


class rate_limit_middleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "127.0.0.1"
        path = request.url.path
        now = time.time()
        limit = _RATE_LIMIT_CHAT if path in _CHAT_PATHS else _RATE_LIMIT_DEFAULT
        cache_key = f"{ip}:{path if path in _CHAT_PATHS else 'default'}"

        async with _rate_limit_lock:
            stale_keys = [k for k, (_, ts) in _rate_limit_cache.items() if now - ts > 86400]
            for k in stale_keys:
                del _rate_limit_cache[k]

            if cache_key in _rate_limit_cache:
                count, start_time = _rate_limit_cache[cache_key]
                if now - start_time > _RATE_LIMIT_WINDOW:
                    _rate_limit_cache[cache_key] = (1, now)
                else:
                    if count >= limit:
                        return JSONResponse(status_code=429, content={"error": "Rate limit exceeded. Too many requests."})
                    _rate_limit_cache[cache_key] = (count + 1, start_time)
            else:
                _rate_limit_cache[cache_key] = (1, now)

        return await call_next(request)
