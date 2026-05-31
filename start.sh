#!/bin/bash

# EDITH Startup Script
# Manages dependencies (SearXNG) and core EDITH processes.

# Function to wait for a URL to become available
wait_for_url() {
    URL=$1
    TIMEOUT=$2
    NAME=$3
    
    echo "Waiting for $NAME to be ready at $URL..."
    
    for ((i=0; i<TIMEOUT; i++)); do
        if curl -s --head --fail "$URL" > /dev/null; then
            echo "$NAME is ready."
            return 0
        fi
        sleep 1
    done
    
    return 1
}

# Cleanup function to run on exit
cleanup() {
    echo -e "\nStopping EDITH..."
    if [ -f /tmp/edith_daemon.pid ]; then
        DAEMON_PID=$(cat /tmp/edith_daemon.pid)
        echo "Killing background daemon (PID: $DAEMON_PID)..."
        kill "$DAEMON_PID" 2>/dev/null
        rm /tmp/edith_daemon.pid
    fi
    if [ -f /tmp/edith_uvicorn.pid ]; then
        UVICORN_PID=$(cat /tmp/edith_uvicorn.pid)
        echo "Killing chat server (PID: $UVICORN_PID)..."
        kill "$UVICORN_PID" 2>/dev/null
        rm /tmp/edith_uvicorn.pid
    elif [ -n "$UVICORN_PID" ]; then
        kill "$UVICORN_PID" 2>/dev/null
    fi
    echo "EDITH stopped."
    exit 0
}

# Trap exit signals to run cleanup
trap cleanup SIGINT SIGTERM

# 1. Check and start SearXNG
echo -e "\n──────────────────────────────────"
echo "Step 1: Starting SearXNG..."
echo "──────────────────────────────────"
if ! curl -s --head --fail "http://localhost:8080/search?q=test" > /dev/null; then
    echo "SearXNG not running. Starting it now via Docker..."
    docker start searxng 2>/dev/null || docker run -d --name searxng -p 8080:8080 searxng/searxng
    if ! wait_for_url "http://localhost:8080/search?q=test" 20 "SearXNG"; then
        echo "Warning: SearXNG failed to start within 20 seconds. Continuing without it."
    fi
else
    echo "SearXNG is already running."
fi

# 2. Activate Python virtual environment
echo -e "\n──────────────────────────────────"
echo "Step 2: Activating Python venv..."
echo "──────────────────────────────────"
VENV_PATH="$HOME/edith-env/bin/activate"
if [ -f "$VENV_PATH" ]; then
    # shellcheck source=/home/vaibhav/edith-env/bin/activate
    source "$VENV_PATH"
    echo "Virtual environment activated."
else
    echo "Error: Virtual environment not found at $VENV_PATH"
    exit 1
fi


# 3. Start background_daemon.py
echo -e "\n──────────────────────────────────"
echo "Step 3: Starting EDITH background daemon..."
echo "──────────────────────────────────"
python "$HOME/EDITH/background_daemon.py" &
DAEMON_PID=$!
echo "$DAEMON_PID" > /tmp/edith_daemon.pid
echo "Background daemon started with PID: $DAEMON_PID"

# 4. Wait for daemon to initialize
echo -e "\n──────────────────────────────────"
echo "Step 4: Waiting for daemon to initialize..."
echo "──────────────────────────────────"
sleep 2
echo "Wait complete."

# 5. Wait for chat server to come up (background_daemon.py starts it internally)
echo -e "\n──────────────────────────────────"
echo "Step 5: Waiting for chat server on port 8001..."
echo "──────────────────────────────────"
if wait_for_url "http://127.0.0.1:8001/api/status" 45 "EDITH chat server"; then
    echo "EDITH is running at http://127.0.0.1:8001"
else
    echo "Warning: Chat server did not respond within 30 seconds. Check logs."
fi

# Keep script running to handle cleanup
wait $DAEMON_PID
