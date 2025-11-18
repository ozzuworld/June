# Building and Testing Orpheus TTS Docker Image

## Quick Build Instructions

### 1. Build the Docker Image

```bash
cd June/services/june-tts

# Build with Orpheus Dockerfile
docker build -f Dockerfile.orpheus -t june-tts:orpheus .
```

**Build Time:**
- First build: ~15-20 minutes
- Models downloaded from HuggingFace: ~3-4GB
- Final image size: ~10-12GB

### 2. Run with GPU Support

```bash
docker run --gpus all \
  -p 8000:8000 \
  -e DB_HOST=100.64.0.1 \
  -e DB_PORT=30432 \
  -e LIVEKIT_IDENTITY=june-tts \
  -e LIVEKIT_ROOM=ozzu-main \
  -e HF_TOKEN=your_huggingface_token \
  june-tts:orpheus
```

### 3. Run without GPU (CPU Mode - Slower)

```bash
docker run \
  -p 8000:8000 \
  -e DB_HOST=100.64.0.1 \
  -e LIVEKIT_IDENTITY=june-tts \
  june-tts:orpheus
```

**Note:** CPU mode will be significantly slower and is not recommended for production.

## Environment Variables

### Required

```bash
# Database (if using voice cloning)
DB_HOST=100.64.0.1
DB_PORT=30432
DB_NAME=june
DB_USER=keycloak
DB_PASSWORD=your_password

# LiveKit
LIVEKIT_IDENTITY=june-tts
LIVEKIT_ROOM=ozzu-main
ORCHESTRATOR_URL=https://api.ozzu.world
```

### Optional (Orpheus Settings)

```bash
# Model Configuration
ORPHEUS_MODEL=canopylabs/orpheus-3b-0.1-ft
ORPHEUS_VARIANT=english  # or "multilingual"

# vLLM Optimization
VLLM_GPU_MEMORY_UTILIZATION=0.7  # 0.0-1.0
VLLM_MAX_MODEL_LEN=2048
VLLM_QUANTIZATION=fp8  # fp8, fp16, or none

# Streaming
ORPHEUS_CHUNK_SIZE=210  # SNAC tokens per chunk
ORPHEUS_FADE_MS=5  # Fade duration (prevents clicks)

# General
WARMUP_ON_STARTUP=1  # Pre-warm model on startup
MAX_WORKERS=2  # Thread pool size
HF_TOKEN=your_token  # For downloading models
```

## Testing the Service

### 1. Health Check

```bash
curl http://localhost:8000/health
```

**Expected Response:**
```json
{
  "status": "ok",
  "mode": "orpheus_tts",
  "model": "canopylabs/orpheus-3b-0.1-ft",
  "device": "cuda",
  "streaming_enabled": true,
  "livekit_connected": true,
  "optimizations": {
    "engine": "orpheus_vllm",
    "expected_latency_ms": "100-200",
    "streaming": true
  }
}
```

### 2. Synthesize Speech

```bash
curl -X POST http://localhost:8000/api/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, this is Orpheus TTS speaking!",
    "room_name": "test-room",
    "voice_id": "default",
    "temperature": 0.7
  }'
```

**Expected Response:**
```json
{
  "status": "success",
  "mode": "orpheus_tts",
  "total_time_ms": 150,
  "audio_duration_seconds": 2.5,
  "performance": {
    "real_time_factor": 0.06,
    "inference_speedup": 16.67
  }
}
```

### 3. Clone a Voice

```bash
curl -X POST http://localhost:8000/api/voices/clone \
  -F "voice_id=my_voice" \
  -F "voice_name=My Custom Voice" \
  -F "file=@reference_audio.wav"
```

### 4. List Voices

```bash
curl http://localhost:8000/api/voices
```

## Performance Benchmarks

### Expected Latency (RTX 4080/4090)

| Text Length | Latency | RTF |
|-------------|---------|-----|
| 10 words | ~150ms | 0.05 |
| 50 words | ~300ms | 0.08 |
| 100 words | ~500ms | 0.12 |

**RTF (Real-Time Factor):** Lower is better. 0.1 means 10x faster than real-time.

### GPU Memory Usage

| Configuration | VRAM Used |
|---------------|-----------|
| FP16 (no quant) | 16-20GB |
| FP8 quantization | 12-16GB |
| Batch size 1 | 12-14GB |
| Batch size 4 | 18-22GB |

## Troubleshooting

### Model Not Loading

**Error:** `ModuleNotFoundError: No module named 'orpheus_tts'`

**Solution:**
```bash
# Verify package is installed in image
docker run june-tts:orpheus python3.11 -c "import orpheus_tts; print('OK')"
```

### GPU Not Detected

**Error:** `WARNING: The NVIDIA Driver was not detected`

**Solution:**
```bash
# Install NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# Test GPU access
docker run --rm --gpus all nvidia/cuda:12.1.0-base nvidia-smi
```

### CUDA Out of Memory

**Error:** `CUDA out of memory`

**Solutions:**
1. Reduce GPU memory utilization:
   ```bash
   -e VLLM_GPU_MEMORY_UTILIZATION=0.5
   ```

2. Use FP8 quantization:
   ```bash
   -e VLLM_QUANTIZATION=fp8
   ```

3. Reduce max model length:
   ```bash
   -e VLLM_MAX_MODEL_LEN=1024
   ```

### Slow First Request

**Issue:** First synthesis takes 30+ seconds

**Expected Behavior:**
- Model loads on startup (~2-3 minutes)
- First generation triggers compilation (WARMUP_ON_STARTUP=1 does this at boot)
- Subsequent requests should be fast (~100-200ms)

**Solution:**
Ensure warmup is enabled:
```bash
-e WARMUP_ON_STARTUP=1
```

### Model Download Fails

**Error:** Connection timeout or 403 Forbidden

**Solution:**
1. Provide Hugging Face token:
   ```bash
   -e HF_TOKEN=your_hf_token
   ```

2. Pre-download models outside Docker:
   ```bash
   huggingface-cli login
   huggingface-cli download canopylabs/orpheus-3b-0.1-ft
   huggingface-cli download hubertsiuzdak/snac_24khz
   ```

3. Mount cache directory:
   ```bash
   docker run --gpus all \
     -v ~/.cache/huggingface:/app/.cache/huggingface \
     -p 8000:8000 \
     june-tts:orpheus
   ```

## Docker Compose (Optional)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  june-tts-orpheus:
    image: june-tts:orpheus
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    ports:
      - "8000:8000"
    environment:
      - DB_HOST=100.64.0.1
      - DB_PORT=30432
      - DB_NAME=june
      - DB_USER=keycloak
      - DB_PASSWORD=Pokemon123!
      - LIVEKIT_IDENTITY=june-tts
      - LIVEKIT_ROOM=ozzu-main
      - ORCHESTRATOR_URL=https://api.ozzu.world
      - ORPHEUS_MODEL=canopylabs/orpheus-3b-0.1-ft
      - VLLM_GPU_MEMORY_UTILIZATION=0.7
      - VLLM_QUANTIZATION=fp8
      - WARMUP_ON_STARTUP=1
      - HF_TOKEN=${HF_TOKEN}
    volumes:
      - huggingface_cache:/app/.cache/huggingface
    restart: unless-stopped

volumes:
  huggingface_cache:
```

Run with:
```bash
docker-compose up -d
```

## Kubernetes Deployment (Optional)

See `ORPHEUS_MIGRATION.md` section for Kubernetes manifests.

## Next Steps

1. ✅ Build image successfully
2. ✅ Test with health check
3. ✅ Test synthesis endpoint
4. ✅ Test voice cloning
5. ✅ Benchmark latency
6. [ ] Deploy to staging
7. [ ] Load testing
8. [ ] Production deployment

## Support

For issues:
1. Check logs: `docker logs <container_id>`
2. Review `ORPHEUS_MIGRATION.md`
3. Check GitHub: https://github.com/canopyai/Orpheus-TTS/issues

---

**Good luck with Orpheus TTS!** 🚀
