import os
from fastapi import Request
from api_auth import is_request_authenticated, create_unauthorized_response

async def api_key_middleware(request: Request, call_next):
    """Validate API key for protected endpoints before CORS processing."""
    # Allow all requests to /api/status and /api/health-check without auth
    if request.url.path in ["/api/status", "/api/health-check", "/api/system-status"]:
        return await call_next(request)

    is_valid, error = is_request_authenticated(request)
    if not is_valid:
        return create_unauthorized_response()
    return await call_next(request)
