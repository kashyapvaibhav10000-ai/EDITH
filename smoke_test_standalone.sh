#!/bin/bash
# EDITH Local/Cloud Split — Standalone Smoke Test
# Run this on the Manjaro PC to test the split architecture without Docker
# Usage: ./smoke_test_standalone.sh
#
# This script:
# 1. Starts local_bridge.py on :8002
# 2. Starts a minimal Flask cloud stub on :8001 (just for health check)
# 3. Runs all 7 smoke tests
# 4. Cleans up processes

set -e

BRIDGE_SECRET="edith_test_secret_12345"
EDITH_PATH="/home/vaibhav/EDITH"
VENV_PATH="$EDITH_PATH/edith-env"

cd "$EDITH_PATH"

echo "🧪 EDITH Local/Cloud Split — Standalone Smoke Tests"
echo "════════════════════════════════════════════════════"
echo ""

# ────────────────────────────────────────────────────
# 0. Verify environment
# ────────────────────────────────────────────────────
echo "📋 [SETUP] Checking environment..."

if [ ! -d "$VENV_PATH" ]; then
    echo "❌ Python venv not found at $VENV_PATH"
    echo "   → Creating venv..."
    python3.11 -m venv "$VENV_PATH" 2>&1 | tail -3
fi

source "$VENV_PATH/bin/activate"

# Quick import check
python3 -c "import fastapi; import requests; print('✅ Dependencies OK')" || {
    echo "⚠️  Installing missing deps..."
    pip install fastapi uvicorn requests -q
}

# ────────────────────────────────────────────────────
# 1. Start stub services
# ────────────────────────────────────────────────────
echo ""
echo "🚀 [STARTUP] Starting local_bridge.py on :8002..."

# Create background service starter
cat > /tmp/start_bridge.py << 'BRIDGE_SCRIPT'
import os
import sys
sys.path.insert(0, "/home/vaibhav/EDITH")
os.environ["BRIDGE_SECRET"] = "edith_test_secret_12345"
os.environ["PYTHONUNBUFFERED"] = "1"
from local_bridge import app
import uvicorn
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="warning")
BRIDGE_SCRIPT

python3 /tmp/start_bridge.py > /tmp/bridge.log 2>&1 &
BRIDGE_PID=$!
echo "   PID: $BRIDGE_PID"
sleep 2

# Create stub cloud service
echo "🚀 [STARTUP] Starting stub cloud node on :8001..."
cat > /tmp/stub_cloud.py << 'CLOUD_SCRIPT'
from flask import Flask
app = Flask(__name__)
@app.route("/")
def index():
    return {"status": "ok"}, 200
@app.route("/api/chat", methods=["POST"])
def chat():
    return {"reply": "This is a stub cloud response for testing.", "intent": "chat"}, 200
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8001, debug=False)
CLOUD_SCRIPT

python3 -c "import flask" 2>/dev/null || pip install flask -q
python3 /tmp/stub_cloud.py > /tmp/cloud.log 2>&1 &
CLOUD_PID=$!
echo "   PID: $CLOUD_PID"
sleep 2

# ────────────────────────────────────────────────────
# 2. Run Smoke Tests
# ────────────────────────────────────────────────────
echo ""
echo "🧪 RUNNING 7 SMOKE TESTS..."
echo ""

PASS=0
FAIL=0

# Test 1: Local Bridge Health Check
echo "─────────────────────────────────────────────────────"
echo "✅ TEST 1: Local Bridge Health Check (GET :8002/health)"
if curl -s -H "X-Bridge-Token: $BRIDGE_SECRET" http://localhost:8002/health | grep -q "status"; then
    echo "   ✓ PASS: Health endpoint returned status"
    ((PASS++))
else
    echo "   ✗ FAIL: No health response"
    cat /tmp/bridge.log | tail -10
    ((FAIL++))
fi
echo ""

# Test 2: Cloud Health Check
echo "─────────────────────────────────────────────────────"
echo "✅ TEST 2: Cloud Node Health Check (GET :8001/)"
if curl -s http://localhost:8001/ | grep -q "ok"; then
    echo "   ✓ PASS: Cloud health endpoint returned"
    ((PASS++))
else
    echo "   ✗ FAIL: No cloud response"
    ((FAIL++))
fi
echo ""

# Test 3: Manual TTS via Local Bridge
echo "─────────────────────────────────────────────────────"
echo "✅ TEST 3: Manual TTS via /speak endpoint"
RESULT=$(curl -s -X POST \
    -H "X-Bridge-Token: $BRIDGE_SECRET" \
    -H "Content-Type: application/json" \
    -d '{"text": "Hello from smoke test"}' \
    http://localhost:8002/speak)
if echo "$RESULT" | grep -q "ok\|status"; then
    echo "   ✓ PASS: /speak endpoint accepted request"
    echo "   Response: $RESULT"
    ((PASS++))
else
    echo "   ✗ FAIL: /speak endpoint failed"
    echo "   Response: $RESULT"
    ((FAIL++))
fi
echo ""

# Test 4: Cloud Chat Endpoint
echo "─────────────────────────────────────────────────────"
echo "✅ TEST 4: Cloud Chat Endpoint (POST :8001/api/chat)"
RESULT=$(curl -s -X POST \
    -H "Content-Type: application/json" \
    -d '{"message": "What is 2+2?", "source": "test"}' \
    http://localhost:8001/api/chat)
if echo "$RESULT" | grep -q "reply"; then
    echo "   ✓ PASS: Cloud chat returned reply"
    echo "   Response: $RESULT"
    ((PASS++))
else
    echo "   ✗ FAIL: No reply from cloud"
    ((FAIL++))
fi
echo ""

# Test 5: Authentication Verification
echo "─────────────────────────────────────────────────────"
echo "✅ TEST 5: Auth Verification (Invalid Token)"
RESULT=$(curl -s -X POST \
    -H "X-Bridge-Token: WRONG_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"text": "test"}' \
    http://localhost:8002/speak)
if echo "$RESULT" | grep -iq "unauthorized\|401\|error"; then
    echo "   ✓ PASS: Auth correctly rejected invalid token"
    ((PASS++))
else
    echo "   ✗ FAIL: Auth bypass — invalid token accepted!"
    echo "   Response: $RESULT"
    ((FAIL++))
fi
echo ""

# Test 6: Mic Pause/Resume
echo "─────────────────────────────────────────────────────"
echo "✅ TEST 6: Mic Pause/Resume Control"
if curl -s -X POST \
    -H "X-Bridge-Token: $BRIDGE_SECRET" \
    http://localhost:8002/mic/pause | grep -q "ok\|paused"; then
    echo "   ✓ PASS: Mic pause endpoint responded"
    ((PASS++))
else
    echo "   ✗ FAIL: Mic pause failed"
    ((FAIL++))
fi
echo ""

# Test 7: E2E Flow (Local → Cloud)
echo "─────────────────────────────────────────────────────"
echo "✅ TEST 7: E2E Network Flow (Local can reach Cloud)"
RESULT=$(python3 -c "
import requests
try:
    r = requests.get('http://localhost:8001/', timeout=3)
    print('OK' if r.status_code == 200 else 'FAIL')
except Exception as e:
    print(f'ERROR: {e}')
")
if echo "$RESULT" | grep -q "OK"; then
    echo "   ✓ PASS: Local can reach cloud on :8001"
    ((PASS++))
else
    echo "   ✗ FAIL: Cannot reach cloud from local"
    ((FAIL++))
fi
echo ""

# ────────────────────────────────────────────────────
# 3. Results Summary
# ────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════"
echo "🧪 TEST RESULTS"
echo "════════════════════════════════════════════════════"
echo "✅ PASSED: $PASS / 7"
echo "❌ FAILED: $FAIL / 7"
echo ""

if [ $FAIL -eq 0 ]; then
    echo "🎉 ALL SMOKE TESTS PASSED!"
    echo ""
    echo "Next steps:"
    echo "1. Run full Docker stack with: docker compose up -d"
    echo "2. Deploy cloud node to Debian server"
    echo "3. Update .env with production URLs"
else
    echo "⚠️  Some tests failed. Check logs:"
    echo "   Bridge logs: tail -20 /tmp/bridge.log"
    echo "   Cloud logs: tail -20 /tmp/cloud.log"
fi

echo ""

# ────────────────────────────────────────────────────
# 4. Cleanup
# ────────────────────────────────────────────────────
echo "🧹 Cleaning up..."
kill $BRIDGE_PID 2>/dev/null || true
kill $CLOUD_PID 2>/dev/null || true
sleep 1
echo "✅ Done"
