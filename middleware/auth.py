"""
middleware/auth.py — API key authentication middleware.

Uses BaseHTTPMiddleware so it registers correctly alongside
logging_middleware and rate_limit_middleware in chat_server.py.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from api_auth import is_request_authenticated, create_unauthorized_response


class api_key_middleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        is_valid, _error = is_request_authenticated(request)
        if not is_valid:
            return create_unauthorized_response()
        return await call_next(request)
