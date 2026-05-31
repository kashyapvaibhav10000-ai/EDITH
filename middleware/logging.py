import time
from starlette.middleware.base import BaseHTTPMiddleware
from config import get_logger

log = get_logger("request_logger")


class logging_middleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        log.info(
            f"\"{request.method} {request.url.path} {request.scope['http_version']}\" "
            f"{response.status_code} | {process_time:.3f}s"
        )
        return response
