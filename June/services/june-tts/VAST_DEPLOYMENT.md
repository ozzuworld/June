# June TTS Deployment on Vast.ai

This guide covers deploying the june-tts service on Vast.ai with the correct two-service architecture.

## Architecture

The TTS service consists of two containers:

1. **fish-speech-server** (port 8080)
   - The actual Fish-Speech TTS engine
   - Handles speech synthesis
   - GPU-accelerated

2. **june-tts** (port 8000)
   - FastAPI wrapper service
   - Provides `/api/tts/synthesize` endpoint
   - Proxies requests to fish-speech-server
   - Compatible with june-orchestrator

## Prerequisites

- Vast.ai GPU instance with CUDA support
- Docker and docker-compose installed
- HuggingFace token (for model downloads)
- GitHub repository cloned

## Deployment Steps

### 1. Stop Current Service

```bash
cd ~/June/June/services/june-vast
# or wherever you're currently running docker-compose

# Stop running containers
docker-compose down

# Optional: Clean up old containers
docker rm -f fish-speech june-tts 2>/dev/null || true
```

### 2. Navigate to TTS Service Directory

```bash
cd ~/June/June/services/june-tts
```

### 3. Pull Latest Changes

```bash
git pull origin master
```

### 4. Set Environment Variables

```bash
# Set your HuggingFace token
export HF_TOKEN="your_huggingface_token_here"

# Verify it's set
echo $HF_TOKEN
```

### 5. Build and Start Services

```bash
# Use the Vast.ai-specific docker-compose file
docker-compose -f docker-compose.vast.yml up -d
```

### 6. Monitor Startup

```bash
# Watch logs from both services
docker-compose -f docker-compose.vast.yml logs -f

# Or monitor specific service
docker logs -f fish-speech
docker logs -f june-tts
```

### 7. Verify Services

#### Check Fish-Speech (port 8080)
```bash
curl http://localhost:8080/v1/health
```

Expected: `{"status":"ok",...}`

#### Check june-tts wrapper (port 8000)
```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok","upstream":{...}}`

#### Test /api/tts/synthesize endpoint
```bash
curl -X POST http://localhost:8000/api/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello world",
    "room_name": "test-room",
    "language": "en",
    "stream": true
  }'
```

Expected: JSON response with `status: "success"`, `chunks_sent`, and `synthesis_time_ms`

## Service Status

### Check Running Containers

```bash
docker ps
```

You should see both:
- `fish-speech` (healthy)
- `june-tts` (healthy)

### Check Health Status

```bash
docker inspect fish-speech --format='{{.State.Health.Status}}'
docker inspect june-tts --format='{{.State.Health.Status}}'
```

Both should show: `healthy`

### Check Port Bindings

```bash
sudo netstat -tulpn | grep -E "(8000|8080)"
```

You should see:
- `0.0.0.0:8080` -> fish-speech
- `0.0.0.0:8000` -> june-tts

## Troubleshooting

### Service Won't Start

```bash
# Check logs for errors
docker-compose -f docker-compose.vast.yml logs

# Check if ports are already in use
sudo netstat -tulpn | grep -E "(8000|8080)"

# Kill any conflicting processes
sudo kill -9 <PID>
```

### Fish-Speech Taking Long to Start

Fish-Speech compiles models on first run, which can take 5-10 minutes. Watch logs:

```bash
docker logs -f fish-speech
```

Wait for: `Startup done, listening server at http://0.0.0.0:8080`

### june-tts Shows Unhealthy

```bash
# Check if it can reach fish-speech
docker exec june-tts curl http://fish-speech-server:8080/v1/health

# Check the adapter logs
docker logs june-tts
```

### Endpoint Returns 404

Make sure you're using the Dockerfile.wrapper:

```bash
# Rebuild the adapter
docker-compose -f docker-compose.vast.yml build june-tts
docker-compose -f docker-compose.vast.yml up -d june-tts
```

## Development Mode

For development, the docker-compose.vast.yml mounts the app code, so you can make changes without rebuilding:

```bash
# Edit files locally
vim app/main.py

# Restart just the adapter
docker-compose -f docker-compose.vast.yml restart june-tts
```

## Production Mode

For production, comment out the volume mount in docker-compose.vast.yml:

```yaml
# volumes:
#   - ./app:/app/app  # COMMENT THIS OUT FOR PRODUCTION
```

Then rebuild:

```bash
docker-compose -f docker-compose.vast.yml build june-tts
docker-compose -f docker-compose.vast.yml up -d
```

## Stopping Services

```bash
# Stop all services
docker-compose -f docker-compose.vast.yml down

# Stop and remove volumes
docker-compose -f docker-compose.vast.yml down -v
```

## External Access

Vast.ai maps internal port 8000 to an external port (e.g., 52696). The orchestrator should connect to:

```
http://YOUR_VAST_IP:EXTERNAL_PORT/api/tts/synthesize
```

Example:
```
http://209.226.130.26:52696/api/tts/synthesize
```

The external port is shown in your Vast.ai instance details.
