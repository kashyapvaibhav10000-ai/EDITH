"""
API Authentication & Authorization for EDITH Chat Server.

Extracted from chat_server.py to isolate authentication logic from route handling.
"""

import os
import hmac
from typing import Optional, Tuple
from fastapi import Request
from fastapi.responses import JSONResponse

# ──────────────────────────────────────────────────
# API Key Configuration
# ──────────────────────────────────────────────────

_keys_raw = os.getenv("EDITH_API_KEYS", "") + "," + os.getenv("EDITH_API_KEY", "")
VALID_API_KEYS = set(filter(None, _keys_raw.split(",")))

import logging as _logging
if not VALID_API_KEYS:
    _logging.getLogger("edith").warning(
        "EDITH_API_KEYS and EDITH_API_KEY are both unset — all protected endpoints will return 401"
    )

# Fail-closed: define PUBLIC paths explicitly. Everything else requires auth.
PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/dashboard",
    "/api/health-check",
    "/api/status",
    "/api/system-status",
    "/api/stats",
    "/api/provider-latencies",
    "/api/costs",
    "/api/monitor_schedule",
    "/api/phone",
    "/api/weather-status",
    "/api/last-memory",
    "/api/traces/recent",
    "/api/recent_traces",
    "/api/logs/stream",
    "/api/mcp/status",
    "/api/sessions",
    "/api/devpanel/modules",
    "/api/devpanel/query",
    "/api/repo/analyses",
    "/api/repo/watched",
    "/api/repo/alert-config",
    "/api/repo/trend",
    "/api/repo/success-rate",
    "/api/repo/subtask-status",
    "/api/repo/adapt-status",
}

PUBLIC_PREFIXES = (
    "/static/",
    "/api/mcp/tools/",
    "/api/sessions/",
    "/api/repo/adapt-status/",
)


# ──────────────────────────────────────────────────
# Authentication Functions
# ──────────────────────────────────────────────────

def is_path_public(path: str) -> bool:
    """
    Fail-closed: only explicitly listed paths are public.
    Everything else requires authentication.
    """
    if path in PUBLIC_PATHS:
        return True
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return True
    return False


def extract_api_key(request: Request) -> Optional[str]:
    """
    Extract API key from request headers.
    Supports both X-API-Key header and Bearer token in Authorization header.
    """
    # Try X-API-Key header first
    api_key = request.headers.get("X-API-Key", "").strip()
    if api_key:
        return api_key
    
    # Try Bearer token in Authorization header
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    
    return None


def validate_api_key(api_key: Optional[str]) -> bool:
    """
    Validate API key against known valid keys using constant-time comparison.
    
    Returns True if key is valid, False otherwise.
    """
    if not api_key or not VALID_API_KEYS:
        return False
    
    # Use constant-time comparison to prevent timing attacks
    return any(hmac.compare_digest(api_key, key) for key in VALID_API_KEYS)


def is_request_authenticated(request: Request) -> Tuple[bool, Optional[str]]:
    """
    Verify request is authenticated or accessing public path.
    
    Returns (is_valid, error_message)
    """
    path = request.url.path
    
    # Public paths bypass authentication
    if is_path_public(path):
        return True, None
    
    # Extract and validate API key
    api_key = extract_api_key(request)
    if validate_api_key(api_key):
        return True, None
    
    return False, "Unauthorized: missing or invalid API key"


def create_unauthorized_response() -> JSONResponse:
    """Create a standard 401 Unauthorized response."""
    return JSONResponse(
        status_code=401,
        content={"error": "Unauthorized: missing or invalid API key"}
    )
