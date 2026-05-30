"""
routes/logs.py — Log streaming endpoint.
  GET /api/logs/stream
"""

import asyncio
import os

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.get("/api/logs/stream")
async def api_logs_stream():
    """SSE endpoint tailing edith.log. Sends last 100 lines on connect then streams new ones."""
    from config import EDITH_PATH as _EDITH_PATH

    log_path = os.path.join(_EDITH_PATH, "logs", "edith.log")

    async def _generate():
        try:
            if os.path.exists(log_path):
                with open(log_path, "r") as f:
                    lines = f.readlines()
                    for line in lines[-100:]:
                        yield f"data: {line.rstrip()}\n\n"

            with open(log_path, "a+") as _:
                pass

            last_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
            while True:
                await asyncio.sleep(0.5)
                if not os.path.exists(log_path):
                    continue
                cur_size = os.path.getsize(log_path)
                if cur_size > last_size:
                    with open(log_path, "r") as f:
                        f.seek(last_size)
                        new_lines = f.read()
                    last_size = cur_size
                    for line in new_lines.splitlines():
                        if line.strip():
                            yield f"data: {line}\n\n"
        except Exception as e:
            yield f"data: [LOG_ERROR] {e}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")
