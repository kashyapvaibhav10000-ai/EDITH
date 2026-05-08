# EDITH Local/Cloud Split — Smoke Test Checklist

## Pre-Test Setup

### 1. Environment Variables
```bash
# Copy .env.example to .env and fill in values
cp .env.example .env.local
cp .env.example .env.cloud

# CRITICAL: Set matching BRIDGE_SECRET in both
export BRIDGE_SECRET="your_secure_token_here"
```

### 2. X11 Display Access (Local Node only)
```bash
# Allow Docker to access host X11 socket
xhost +local:

# Verify DISPLAY is set
echo $DISPLAY  # Should output ":0" or similar
```

### 3. Build + Start Containers
```bash
# Build images
docker compose -f docker-compose.phase1-test.yml build

# Start services
docker compose -f docker-compose.phase1-test.yml up -d

# Wait for startup (30s)
sleep 30

# Check logs
docker logs edith-local-node
docker logs edith-cloud-node
```

---

## Smoke Tests

### ✅ Test 1: Local Bridge Health Check
```bash
# Should return {"status": "ok"}
curl -H "X-Bridge-Token: your_secure_token_here" \
  http://localhost:8002/health

# Expected output:
# {"status":"ok","service":"local-bridge"}
```

### ✅ Test 2: Cloud Node Health Check
```bash
# Should return 200 OK
curl http://localhost:8001/

# Or check dashboard
curl http://localhost:8001/dashboard
```

### ✅ Test 3: Manual TTS via Local Bridge
```bash
# Test /speak endpoint
curl -X POST \
  -H "X-Bridge-Token: your_secure_token_here" \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from the local bridge"}' \
  http://localhost:8002/speak

# 🔊 You should hear audio output (Piper TTS or system speaker)
# Check logs for: "Spoke: Hello from..."
```

### ✅ Test 4: Manual Chat via Cloud
```bash
# Send a test message to cloud
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the weather today?", "source": "voice"}' \
  http://localhost:8001/api/chat

# Should return:
# {"reply": "...weather response...", "intent": "search", ...}
```

### ✅ Test 5: Wake Word Detection (Manual)
```bash
# Option A: Manually trigger wake_listener (if running standalone)
# Say "hey edith" into microphone
# Watch docker logs edith-local-node for:
# [WAKE] 🎯 WAKE WORD DETECTED!

# Option B: If running in Docker with audio, speak into host mic
# Logs should show:
# Transcribed: 'your voice input'
# Cloud POST request to http://cloud-node:8001/api/chat
# Response received: [cloud reply]
```

### ✅ Test 6: Full E2E Flow (Docker-to-Docker)
```bash
# From local-node container, test cloud connectivity
docker exec edith-local-node bash -c \
  'curl -X POST \
   -H "Content-Type: application/json" \
   -d "{\"message\": \"test\", \"source\": \"voice\"}" \
   http://cloud-node:8001/api/chat'

# Should return cloud response
```

### ✅ Test 7: Mic Pause/Resume
```bash
# Pause wake_listener (e.g., when browser mic active)
curl -X POST \
  -H "X-Bridge-Token: your_secure_token_here" \
  http://localhost:8002/mic/pause

# Resume
curl -X POST \
  -H "X-Bridge-Token: your_secure_token_here" \
  http://localhost:8002/mic/resume

# Check logs for: "Wake listener paused."
```

---

## Troubleshooting

### Audio Not Working (Local Node)
```bash
# 1. Check /dev/snd passthrough
docker exec edith-local-node ls -la /dev/snd

# 2. Check ALSA devices
docker exec edith-local-node arecord -l  # Playback devices
docker exec edith-local-node aplay -l     # Recording devices

# 3. Test espeak-ng fallback
docker exec edith-local-node espeak-ng "Test audio"

# 4. Check Piper TTS
docker exec edith-local-node which piper
docker exec edith-local-node piper --help
```

### X11 Display Not Found (PyQt6 Widget)
```bash
# 1. Ensure X11 socket is mounted
docker exec edith-local-node ls -la /tmp/.X11-unix

# 2. Check DISPLAY env var
docker exec edith-local-node echo $DISPLAY

# 3. If still fails, try running without widget (local_bridge only)
# The bridge should still work for voice I/O
```

### Cloud Can't Reach Local Bridge
```bash
# 1. Test network connectivity (docker logs should show)
docker exec edith-cloud-node curl http://local-node:8002/health

# 2. Check BRIDGE_SECRET in both containers
docker exec edith-cloud-node echo $BRIDGE_SECRET
docker exec edith-local-node echo $BRIDGE_SECRET
# Should match exactly

# 3. If using production: ensure firewall allows port 8002
# sudo ufw allow 8002/tcp
```

### Cloud Chat Endpoint Returns Error
```bash
# Check cloud-node logs
docker logs edith-cloud-node --tail 50

# Common errors:
# - Missing LLM API keys (GROQ_API_KEY, OPENAI_API_KEY, etc.)
#   → Set in .env.cloud
# - ChromaDB write errors
#   → Check memory_db volume mount
# - orchestrator.speak() connection failure
#   → Verify LOCAL_BRIDGE_URL = http://local-node:8002
```

---

## Production Deployment (After Local Tests Pass)

### Move Cloud Node to Debian Server

1. **Export cloud container + volumes**
   ```bash
   # On Docker machine
   docker save edith-cloud-node:latest | gzip > edith-cloud.tar.gz
   docker run --rm -v edith-chromadb:/data \
     -v edith-sqlite:/db \
     alpine tar czf - -C / data db | gzip > edith-volumes.tar.gz
   
   # Transfer to Debian server
   scp edith-cloud.tar.gz user@debian-server:/tmp/
   scp edith-volumes.tar.gz user@debian-server:/tmp/
   ```

2. **On Debian Server**
   ```bash
   # Load container + volumes
   docker load < /tmp/edith-cloud.tar.gz
   
   # Restore volumes
   docker run --rm -i -v edith-chromadb:/data -v edith-sqlite:/db \
     alpine tar xzf - -C / < /tmp/edith-volumes.tar.gz
   
   # Run cloud service
   docker run -d \
     --restart always \
     --name edith-cloud-prod \
     -p 8001:8001 \
     -e CLOUD_URL=http://cloud-server-ip:8001 \
     -e LOCAL_BRIDGE_URL=https://local.edith.example.com:8002 \
     -e BRIDGE_SECRET="your_secure_token" \
     -e GROQ_API_KEY="..." \
     -e TELEGRAM_BOT_TOKEN="..." \
     -v edith-chromadb:/edith/memory_db \
     -v edith-sqlite:/edith/memory_db_archive \
     edith-cloud-node:latest
   ```

3. **Update Local Node Environment**
   ```bash
   # .env.local on Manjaro PC
   CLOUD_URL=https://cloud.edith.example.com  # Update to production domain
   LOCAL_BRIDGE_URL=http://localhost:8002      # Stays local
   BRIDGE_SECRET="your_secure_token"           # Same as cloud
   ```

4. **Use HTTPS + SSL (Production)**
   ```bash
   # Deploy nginx reverse proxy with Let's Encrypt
   # aws_proxy.conf → forward :8001 to local docker
   # ssl_certificate → /etc/letsencrypt/live/cloud.edith.example.com/
   ```

---

## Success Criteria

All of the following must pass:

- ✅ `/health` endpoints return 200
- ✅ Manual `/speak` produces audio
- ✅ Wake word detection logs appear
- ✅ Cloud chat endpoint responds in < 10 seconds
- ✅ Local bridge receives response + speaks it
- ✅ No errors in container logs related to auth, connection, or imports

---

## Next Steps

Once all smoke tests pass:

1. **Stop local docker simulation**
   ```bash
   docker compose -f docker-compose.phase1-test.yml down
   ```

2. **Deploy to production**
   - Run local-node on Manjaro PC (standalone or systemd service)
   - Deploy cloud-node to Debian server
   - Update `.env` with production URLs

3. **Monitor in production**
   - Watch `docker logs edith-cloud-prod -f`
   - Check `/api/health` endpoints regularly
   - Monitor ChromaDB + SQLite storage capacity

4. **scale to multi-local**
   - Run multiple local-node instances (different homes/offices)
   - All post to same cloud server
   - Cloud maintains shared memory + user context
