"""
LEGACY: this server is kept for backward compatibility only.
Primary server is chat_server.py on port 8001.
"""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import uvicorn

from dashboard_routes import register_dashboard_routes

app = FastAPI()

# Register all dashboard API routes
register_dashboard_routes(app)

@app.get("/")
def dashboard():
    """Redirect to main dashboard on port 8001."""
    return RedirectResponse(
        url="http://127.0.0.1:8001/dashboard",
        status_code=307,
        headers={"X-EDITH-Notice": "Main dashboard moved to 8001"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)