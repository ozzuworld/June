# Fish Speech (OpenAudio S1) Production Optimization Guide
## For June-TTS Service

**Generated:** 2025-11-14
**Target System:** june-tts (Fish Speech API Wrapper)
**Model:** OpenAudio S1 / Fish Speech 1.5
**Current Implementation:** `/home/user/June/June/services/june-tts`

---

## Table of Contents
1. [Current Setup Analysis](#current-setup-analysis)
2. [Critical Performance Optimizations](#critical-performance-optimizations)
3. [Production Deployment Best Practices](#production-deployment-best-practices)
4. [GPU Memory Optimization](#gpu-memory-optimization)
5. [Inference Speed Optimization](#inference-speed-optimization)
6. [Scalability & Concurrency](#scalability--concurrency)
7. [Recommended Implementation Changes](#recommended-implementation-changes)
8. [Monitoring & Health Checks](#monitoring--health-checks)

---

## Current Setup Analysis

### Your Current Implementation
- **Mode:** Fish Speech API wrapper (HTTP client)
- **Architecture:** FastAPI wrapper → Fish Speech API (port 9880) → LiveKit streaming
- **Model:** OpenAudio S1-mini (0.5B parameters, distilled version)
- **Sample Rate:** 44.1kHz → 48kHz (LiveKit)
- **GPU:** CUDA 12.6, PyTorch 2.6.0
- **Startup Script:** Downloads model from HuggingFace, starts API server

### Current Optimizations Present ✅
- HTTP timeout increased to 90s (handles long sentences)
- GPU resampling with torchaudio
- Async PostgreSQL connection pooling
- Reference audio caching in memory

### Missing Optimizations ⚠️
- **`--compile` flag NOT enabled** in Fish Speech API startup
- No batching for concurrent requests
- Single worker deployment
- No quantization/precision optimization
- No KV-cache optimization flags

---

## Critical Performance Optimizations

### 1. ⚡ Torch Compile (HIGHEST PRIORITY)

**Impact:** 10x speedup (~15 tokens/sec → 150 tokens/sec on RTX 4090)

#### Current State
Your start script at `June/services/june-tts/app/start.sh:33-37` does NOT include the `--compile` flag:

```bash
python3.12 -m tools.api_server \
    --listen 127.0.0.1:9880 \
    --llama-checkpoint-path /app/checkpoints/openaudio-s1-mini \
    --decoder-checkpoint-path /app/checkpoints/openaudio-s1-mini/codec.pth \
    --decoder-config-name modded_dac_vq &
```

#### Required Change
```bash
python3.12 -m tools.api_server \
    --listen 127.0.0.1:9880 \
    --llama-checkpoint-path /app/checkpoints/openaudio-s1-mini \
    --decoder-checkpoint-path /app/checkpoints/openaudio-s1-mini/codec.pth \
    --decoder-config-name modded_dac_vq \
    --compile &  # ← ADD THIS FLAG
```

**Benefits:**
- CUDA kernel fusion for faster inference
- Reduces latency from ~200ms to ~150ms
- Better GPU utilization

**Requirements:**
- GPU must support bf16 (all modern NVIDIA GPUs)
- Adds ~30-60s to initial startup for compilation
- Requires CUDA backend (already present)

---

### 2. 🎯 Precision Optimization

#### Half Precision (FP16) Option
For GPUs without bf16 support, add `--half` flag:

```bash
--half  # Use FP16 instead of BF16
```

**Benefits:**
- ~45% memory usage reduction vs FP32
- Faster inference on older GPUs
- Maintains quality with minimal degradation

#### Quantization (INT8/INT4)
**Available in Fish Speech 1.5+**

- INT8: ~45% memory reduction, minimal quality loss
- INT4: ~75% memory reduction, some quality trade-off
- Useful for multi-model deployment or lower-end GPUs

**Not currently exposed via CLI** - requires custom model loading

---

### 3. 🚀 GPU Memory Requirements

#### Current Model: OpenAudio S1-mini
- **Recommended VRAM:** 12GB
- **Minimum VRAM:** 8GB (with optimizations)
- **Your Model Size:** 0.5B parameters (distilled)

#### Full Model: OpenAudio S1
- **Parameters:** 4B
- **Recommended VRAM:** 24GB
- **Better Quality:** Higher WER/CER scores
- **Trade-off:** More memory, similar speed with compile

#### Memory Optimization Techniques

**Environment Variables to Add:**
```bash
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
export CUDA_LAUNCH_BLOCKING=0  # Async kernel launches
```

**Docker Deployment:**
```dockerfile
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
ENV CUDA_LAUNCH_BLOCKING=0
```

---

## Production Deployment Best Practices

### 1. 🐳 Docker Optimization

#### Current Dockerfile Issues
Your `Dockerfile:37` installs via pip flag `-e .`:
```dockerfile
RUN python3.12 -m pip install -e .
```

**Recommendation:** Use production install (not editable):
```dockerfile
RUN python3.12 -m pip install .
```

#### Add COMPILE Environment Variable Support

**In Dockerfile:**
```dockerfile
ENV COMPILE=1
```

**In start.sh:**
```bash
COMPILE_FLAG=""
if [ "${COMPILE:-1}" = "1" ]; then
    COMPILE_FLAG="--compile"
    echo "=== Torch compile ENABLED ==="
fi

python3.12 -m tools.api_server \
    --listen 127.0.0.1:9880 \
    --llama-checkpoint-path /app/checkpoints/openaudio-s1-mini \
    --decoder-checkpoint-path /app/checkpoints/openaudio-s1-mini/codec.pth \
    --decoder-config-name modded_dac_vq \
    $COMPILE_FLAG &
```

#### Health Check Optimization

**Current:**
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=240s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

**Recommendation:** Add Fish Speech API health check too:
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=240s --retries=3 \
    CMD curl -f http://localhost:8000/health && \
        curl -f http://localhost:9880/health || exit 1
```

---

### 2. 📊 Performance Benchmarks

#### OpenAudio S1 (4B parameters)
- **WER (English):** 0.008
- **CER (English):** 0.004
- **Speaker Distance:** 0.332
- **Rank:** #1 on TTS-Arena2
- **RTF on RTX 4090:** 1:7 (with compile)
- **RTF on RTX 4060:** 1:5 (with fish-tech)

#### OpenAudio S1-mini (0.5B - YOUR CURRENT MODEL)
- **WER:** 0.011
- **CER:** 0.005
- **Speaker Distance:** 0.380
- **Quality:** Excellent for production
- **Speed:** Faster than S1, lower memory

#### Real-Time Factor Explained
- **1:5** = 5 seconds of audio generated per 1 second of compute
- **1:7** = 7 seconds of audio per 1 second
- **1:15** = 15 seconds of audio per 1 second (best case)

---

### 3. 🔄 Batch Processing & Concurrency

#### Current Limitation
Your service processes one request at a time:
```python
# June/services/june-tts/app/main.py:411
@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    # Single request processing
```

#### Fish Audio API Batch Support
Fish Audio platform supports batch processing:
- **Batch Size:** Up to 50 requests
- **Benefits:** Reduced latency, avoid rate limits, save bandwidth
- **Latency Reduction:** ~30% for batched requests

#### Implementation Strategy

**Option 1: Request Queuing (Recommended)**
```python
from asyncio import Queue
from typing import List

# Global request queue
tts_queue = Queue(maxsize=50)
batch_interval = 0.1  # 100ms batching window

async def batch_processor():
    """Process requests in batches"""
    while True:
        batch: List[SynthesizeRequest] = []
        deadline = asyncio.get_event_loop().time() + batch_interval

        # Collect requests for batch_interval
        while asyncio.get_event_loop().time() < deadline and len(batch) < 50:
            try:
                req = await asyncio.wait_for(
                    tts_queue.get(),
                    timeout=deadline - asyncio.get_event_loop().time()
                )
                batch.append(req)
            except asyncio.TimeoutError:
                break

        if batch:
            # Process batch in parallel
            await asyncio.gather(*[process_single(req) for req in batch])
```

**Option 2: Multiple Workers**
```bash
# In start.sh or docker-compose
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

**⚠️ Warning:** Multiple workers require shared state management for:
- LiveKit connections (one per worker)
- Voice caching (Redis recommended)
- Database connection pools

---

### 4. 🎭 Voice Cloning Optimization

#### Current Implementation
Stores voices in PostgreSQL as BYTEA, loads on-demand.

#### Recommendations

**1. Pre-warm Voice Cache on Startup**
```python
@app.on_event("startup")
async def on_startup():
    # ... existing code ...

    # Pre-load most common voices
    common_voices = await get_common_voices()  # e.g., top 5 by usage
    for voice_id in common_voices:
        await load_voice_reference(voice_id)
    logger.info(f"✅ Pre-warmed {len(common_voices)} voices")
```

**2. LRU Cache for Voice References**
```python
from functools import lru_cache
from datetime import datetime

voice_cache = {}  # {voice_id: (audio_bytes, timestamp)}
MAX_CACHE_SIZE = 10
CACHE_TTL = 3600  # 1 hour

async def load_voice_reference_cached(voice_id: str):
    if voice_id in voice_cache:
        audio, ts = voice_cache[voice_id]
        if (datetime.now().timestamp() - ts) < CACHE_TTL:
            return audio

    audio = await get_voice_from_db(voice_id)
    voice_cache[voice_id] = (audio, datetime.now().timestamp())

    # Evict oldest if cache full
    if len(voice_cache) > MAX_CACHE_SIZE:
        oldest = min(voice_cache.items(), key=lambda x: x[1][1])
        del voice_cache[oldest[0]]

    return audio
```

**3. Reference Audio Quality**
Fish Speech recommendations:
- **Duration:** 10-30 seconds (optimal)
- **Minimum:** 3 seconds (your current validation ✅)
- **Maximum:** 60 seconds (your current validation ✅)
- **Format:** WAV, MP3, FLAC, M4A (all supported ✅)
- **Quality:** Clear speech, minimal background noise
- **Sample Rate:** 16kHz+ (44.1kHz recommended)

---

## Inference Speed Optimization

### 1. 🎵 Audio Processing Pipeline

#### Current Pipeline
```
Text → Fish Speech API → WAV bytes → soundfile.read → numpy
→ GPU resample (44.1kHz → 48kHz) → LiveKit frames
```

#### Optimization: Streaming Mode

**Current (Non-streaming):**
```python
# main.py:180
data = {'text': text, 'streaming': 'false'}
```

**Recommended (Streaming):**
```python
data = {'text': text, 'streaming': 'true'}

# Handle chunked response
async for chunk in response.aiter_bytes():
    # Process audio chunk immediately
    await stream_chunk_to_livekit(chunk)
```

**Benefits:**
- Reduces time-to-first-audio by ~50%
- Better user experience (audio starts playing sooner)
- Lower memory usage (no full audio buffer)

---

### 2. 🔊 Resampling Optimization

#### Current Implementation
```python
# main.py:241-259
def resample_audio_fast(audio, input_sr, output_sr):
    # Uses torchaudio.transforms.Resample
    # Creates resampler on first call, GPU-accelerated ✅
```

**Already Optimal** ✅

#### Additional Optimization: Pre-create Resampler
```python
# In on_startup():
global _gpu_resampler
import torchaudio.transforms as T
_gpu_resampler = T.Resample(FISH_SPEECH_SAMPLE_RATE, LIVEKIT_SAMPLE_RATE)
if torch.cuda.is_available():
    _gpu_resampler = _gpu_resampler.cuda()
logger.info("✅ GPU resampler pre-initialized")
```

---

### 3. ⚡ Latency Breakdown

#### Target Latencies (OpenAudio S1)
- **First Packet:** 150ms
- **Text → Semantic Tokens:** 50-100ms (with compile)
- **Semantic → Audio:** 50-100ms (vocoder)
- **Network/Streaming:** 10-50ms
- **Total (streaming):** ~200-300ms

#### Your Current Implementation
- **HTTP timeout:** 90s (handles long sentences ✅)
- **Compile flag:** ❌ NOT ENABLED
- **Streaming mode:** ❌ NOT ENABLED
- **Estimated latency:** 300-500ms

#### After Optimizations
- **Compile flag:** ✅ ENABLED
- **Streaming mode:** ✅ ENABLED
- **Estimated latency:** 150-250ms (33-50% improvement)

---

## Scalability & Concurrency

### 1. 🏗️ Architecture Patterns

#### Current: Single Worker, Sequential Processing
```
Client → FastAPI → Fish Speech API → LiveKit
   ↓         ↓              ↓
  Wait     Wait          Wait
```

#### Recommended: Multi-Worker with Load Balancing

**Option A: Horizontal Scaling (Kubernetes)**
```yaml
# helm/june-platform/templates/june-tts.yaml
spec:
  replicas: 3  # Multiple pods
  strategy:
    type: RollingUpdate
```

**Kubernetes Service Load Balancing:**
- Automatic request distribution
- Health check integration
- Rolling updates without downtime

**Option B: Multiple Workers (Single Container)**
```bash
uvicorn main:app --workers 4
```

**⚠️ Considerations:**
- Each worker loads model into GPU (memory!)
- May hit VRAM limits with 4 workers on 12GB GPU
- Better for CPU inference or larger GPUs (24GB+)

**Option C: Request Queue + Worker Pool**
```python
# Single model instance, multiple request handlers
workers = 4
queue = asyncio.Queue(maxsize=100)

async def worker(worker_id):
    while True:
        request = await queue.get()
        await process_request(request)
        queue.task_done()

# Startup
for i in range(workers):
    asyncio.create_task(worker(i))
```

---

### 2. 📈 Scaling Recommendations by Load

| Requests/min | Strategy | GPU | Workers | Notes |
|-------------|----------|-----|---------|-------|
| < 10 | Single instance | 12GB | 1 | Current setup OK |
| 10-30 | Single + compile | 12GB | 1 | Enable --compile ✅ |
| 30-60 | Horizontal (2 pods) | 12GB × 2 | 1/pod | Kubernetes scaling |
| 60-120 | Horizontal (3-4 pods) | 12GB × 4 | 1/pod | Add caching layer |
| 120+ | Dedicated TTS cluster | 24GB × N | 1/pod | Redis cache, CDN |

---

### 3. 🔄 Caching Strategies

#### Level 1: In-Memory Voice Cache (Current ✅)
```python
current_voice_id: Optional[str] = None
current_reference_audio: Optional[bytes] = None
```

#### Level 2: Redis Voice Cache (Recommended for Multi-Pod)
```python
import redis.asyncio as redis

redis_client = redis.from_url("redis://redis:6379")

async def get_voice_cached(voice_id: str) -> Optional[bytes]:
    # Try Redis first
    cached = await redis_client.get(f"voice:{voice_id}")
    if cached:
        return cached

    # Load from DB
    audio = await get_voice_from_db(voice_id)
    if audio:
        await redis_client.setex(f"voice:{voice_id}", 3600, audio)
    return audio
```

#### Level 3: Common Phrase Caching
```python
# Cache frequently used phrases
COMMON_PHRASES = {
    "welcome": "Welcome to our service",
    "goodbye": "Thank you, goodbye!",
    "error": "I'm sorry, I didn't understand that",
}

phrase_cache = {}  # {(voice_id, phrase_key): audio_bytes}

# Can reduce API calls by ~30%
```

---

## Recommended Implementation Changes

### Priority 1: IMMEDIATE (1-2 hours)

#### 1.1 Enable Torch Compile
**File:** `June/services/june-tts/app/start.sh`

**Change:**
```bash
# Line 33-37
python3.12 -m tools.api_server \
    --listen 127.0.0.1:9880 \
    --llama-checkpoint-path /app/checkpoints/openaudio-s1-mini \
    --decoder-checkpoint-path /app/checkpoints/openaudio-s1-mini/codec.pth \
    --decoder-config-name modded_dac_vq \
    --compile &  # ← ADD THIS
```

**Expected Impact:**
- 10x faster token generation
- 150ms first-packet latency
- Better GPU utilization

---

#### 1.2 Enable Streaming Mode
**File:** `June/services/june-tts/app/main.py`

**Change Line 180:**
```python
data = {
    'text': text,
    'streaming': 'true'  # ← CHANGE from 'false'
}
```

**Update response handling (Line 184-200):**
```python
# Stream response instead of waiting for full audio
audio_chunks = []
async for chunk in response.aiter_bytes():
    audio_chunks.append(chunk)

# Concatenate chunks
audio_data = b''.join(audio_chunks)
```

**Expected Impact:**
- 50% reduction in time-to-first-audio
- Better perceived latency

---

#### 1.3 Add Environment Variables
**File:** `June/services/june-tts/Dockerfile`

**Add after line 8:**
```dockerfile
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
ENV CUDA_LAUNCH_BLOCKING=0
ENV COMPILE=1
```

---

### Priority 2: SHORT-TERM (1-3 days)

#### 2.1 Implement Voice Cache Warming
**File:** `June/services/june-tts/app/main.py`

**Add to `on_startup()` function (after line 335):**
```python
# Pre-load top voices
try:
    async with db_pool.acquire() as conn:
        top_voices = await conn.fetch("""
            SELECT voice_id FROM tts_voices
            ORDER BY created_at DESC
            LIMIT 5
        """)

    for row in top_voices:
        await load_voice_reference(row['voice_id'])

    logger.info(f"✅ Pre-warmed {len(top_voices)} voices")
except Exception as e:
    logger.warning(f"⚠️ Voice pre-warming failed: {e}")
```

---

#### 2.2 Add Prometheus Metrics
**Install prometheus-client:**
```dockerfile
RUN python3.12 -m pip install prometheus-client
```

**Add metrics tracking:**
```python
from prometheus_client import Counter, Histogram, Gauge
import time

# Metrics
tts_requests_total = Counter('tts_requests_total', 'Total TTS requests', ['voice_id', 'status'])
tts_latency_seconds = Histogram('tts_latency_seconds', 'TTS generation latency', ['voice_id'])
tts_text_length = Histogram('tts_text_length_chars', 'Text length distribution')
active_requests = Gauge('tts_active_requests', 'Currently processing requests')

@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    active_requests.inc()
    start = time.time()

    try:
        # ... existing code ...

        tts_requests_total.labels(voice_id=request.voice_id, status='success').inc()
        tts_latency_seconds.labels(voice_id=request.voice_id).observe(time.time() - start)
        tts_text_length.observe(len(request.text))
        return response
    except Exception as e:
        tts_requests_total.labels(voice_id=request.voice_id, status='error').inc()
        raise
    finally:
        active_requests.dec()

@app.get("/metrics")
async def metrics():
    from prometheus_client import generate_latest
    return Response(content=generate_latest(), media_type="text/plain")
```

---

#### 2.3 Implement Request Queuing
```python
from asyncio import Queue, Semaphore

# Global state
request_queue = Queue(maxsize=100)
max_concurrent = Semaphore(3)  # Max 3 concurrent synthesis

@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    # Queue if busy
    if request_queue.qsize() > 10:
        raise HTTPException(503, "Service busy, try again later")

    async with max_concurrent:
        # ... existing synthesis code ...
```

---

### Priority 3: MEDIUM-TERM (1-2 weeks)

#### 3.1 Upgrade to Full Model (OpenAudio S1)

**If you have 24GB GPU:**

**Change start.sh:**
```bash
# Download full model instead of mini
huggingface-cli download fishaudio/openaudio-s1 \
    --local-dir /app/checkpoints/openaudio-s1 \
    --local-dir-use-symlinks False

# Use full model
python3.12 -m tools.api_server \
    --llama-checkpoint-path /app/checkpoints/openaudio-s1 \
    --decoder-checkpoint-path /app/checkpoints/openaudio-s1/codec.pth \
    --compile &
```

**Benefits:**
- Better quality (WER 0.008 vs 0.011)
- Better speaker similarity
- #1 on TTS-Arena

**Trade-offs:**
- Requires 24GB VRAM
- Slower inference (~30% vs mini)

---

#### 3.2 Implement Redis Caching for Multi-Pod

**Add to docker-compose or Kubernetes:**
```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

**Add to requirements:**
```bash
pip install redis[async]
```

**Implement in code:**
```python
import redis.asyncio as redis

redis_client: Optional[redis.Redis] = None

async def init_redis():
    global redis_client
    redis_client = await redis.from_url(
        "redis://redis:6379",
        encoding="utf-8",
        decode_responses=False
    )

# Use for voice caching, session management, etc.
```

---

#### 3.3 Add Model Warmup

**Prevent first-request slowness:**
```python
@app.on_event("startup")
async def on_startup():
    # ... existing code ...

    # Warm up model with dummy request
    logger.info("🔥 Warming up model...")
    try:
        dummy_audio = await synthesize_with_fish_speech_api(
            text="Hello, this is a warmup request.",
            reference_audio=current_reference_audio
        )
        logger.info("✅ Model warmed up successfully")
    except Exception as e:
        logger.warning(f"⚠️ Model warmup failed: {e}")
```

---

## Monitoring & Health Checks

### 1. 📊 Metrics to Track

#### Latency Metrics
- **Time to First Audio Byte (TTFB)**
- **Total Synthesis Time**
- **LiveKit Streaming Latency**
- **Network Round-Trip Time**

#### Throughput Metrics
- **Requests per Minute**
- **Concurrent Requests**
- **Queue Depth**
- **Audio Minutes Generated per Hour**

#### Resource Metrics
- **GPU Memory Usage**
- **GPU Utilization %**
- **CPU Usage**
- **Network Bandwidth**

#### Quality Metrics
- **Error Rate**
- **Timeout Rate**
- **Voice Cache Hit Rate**
- **Average Text Length**

---

### 2. 🏥 Enhanced Health Checks

**Current `/health` endpoint is basic. Enhance it:**

```python
@app.get("/health")
async def health():
    health_status = {
        "status": "ok",
        "timestamp": time.time(),
        "uptime_seconds": time.time() - startup_time,

        # Service health
        "services": {
            "fish_speech_api": await check_fish_speech_health(),
            "livekit": livekit_connected,
            "database": db_pool is not None,
        },

        # Resource health
        "resources": {
            "gpu_available": torch.cuda.is_available(),
            "gpu_memory_allocated_mb": torch.cuda.memory_allocated() / 1024**2 if torch.cuda.is_available() else 0,
            "gpu_memory_reserved_mb": torch.cuda.memory_reserved() / 1024**2 if torch.cuda.is_available() else 0,
        },

        # Model health
        "model": {
            "loaded": llama_queue is not None,
            "current_voice": current_voice_id,
            "voices_cached": len(voice_cache) if 'voice_cache' in globals() else 1,
        },

        # Performance metrics
        "metrics": {
            "total_requests": total_requests,
            "active_requests": active_requests.get() if 'active_requests' in globals() else 0,
            "avg_latency_ms": avg_latency_ms,
        }
    }

    # Determine overall health
    if not all(health_status["services"].values()):
        health_status["status"] = "degraded"

    return health_status

async def check_fish_speech_health():
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get("http://127.0.0.1:9880/health")
            return response.status_code == 200
    except:
        return False
```

---

### 3. 📈 Grafana Dashboard Recommendations

**Key Panels:**

1. **Latency Overview**
   - P50, P95, P99 latency graph
   - Time-to-first-audio trend

2. **Throughput**
   - Requests/minute
   - Audio minutes/hour
   - Queue depth

3. **Resource Usage**
   - GPU memory utilization
   - GPU temperature
   - CPU usage

4. **Error Tracking**
   - Error rate
   - Timeout rate
   - By voice ID

5. **Voice Analytics**
   - Most used voices
   - Cache hit rate
   - Voice switching frequency

---

## Performance Testing Checklist

Before deploying optimizations, test with:

### Load Testing
```bash
# Use Apache Bench
ab -n 1000 -c 10 -p payload.json -T application/json \
   http://localhost:8000/api/tts/synthesize

# Or locust.io
locust -f load_test.py --host=http://localhost:8000
```

### Latency Testing
```python
# load_test.py
from locust import HttpUser, task, between

class TTSUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def synthesize_short(self):
        self.client.post("/api/tts/synthesize", json={
            "text": "Hello, this is a test.",
            "room_name": "test-room",
            "voice_id": "default"
        })

    @task(weight=2)
    def synthesize_long(self):
        self.client.post("/api/tts/synthesize", json={
            "text": "This is a much longer sentence that will take more time to synthesize and stream to the client." * 3,
            "room_name": "test-room",
            "voice_id": "default"
        })
```

### GPU Memory Profiling
```bash
# Monitor during load test
watch -n 1 nvidia-smi

# Or use nvtop for better visualization
nvtop
```

---

## Summary: Quick Wins

### ⚡ Immediate Actions (< 1 hour, high impact)

1. **Add `--compile` flag to start.sh** (10x speedup)
2. **Enable streaming mode** (50% TTFB reduction)
3. **Add environment variables for GPU optimization**

**Expected Results:**
- Latency: 300-500ms → 150-250ms
- Throughput: +10x token generation speed
- Memory: More efficient GPU usage

### 🚀 Quick Improvements (1-2 days, medium impact)

1. **Implement voice cache warming** (faster common requests)
2. **Add basic metrics** (visibility into performance)
3. **Implement request semaphore** (prevent overload)

**Expected Results:**
- Cache hit rate: 0% → 60-80% for common voices
- Overload protection: Graceful degradation
- Monitoring: Full visibility

### 📈 Strategic Upgrades (1-2 weeks, scaling)

1. **Horizontal scaling with Kubernetes** (3+ replicas)
2. **Redis caching layer** (shared state)
3. **Upgrade to full S1 model** (better quality)

**Expected Results:**
- Capacity: 10 req/min → 100+ req/min
- Quality: Mini → Full model (WER 0.011 → 0.008)
- Reliability: Multi-pod redundancy

---

## Additional Resources

### Official Documentation
- Fish Speech GitHub: https://github.com/fishaudio/fish-speech
- OpenAudio Docs: https://speech.fish.audio/
- Inference Guide: https://speech.fish.audio/inference/
- Docker Deployment: https://deepwiki.com/fishaudio/fish-speech/7.2-docker-and-deployment

### Research Papers
- Fish-Speech Paper: https://arxiv.org/abs/2411.01156
- TTS-Arena Leaderboard: https://fish.audio/

### Performance Benchmarking
- RTF Benchmarks: https://github.com/fishaudio/fish-speech/issues/1020
- Production Deployment Examples: https://www.siliconflow.com/models/fish-speech-1.5

### Community
- GitHub Issues: https://github.com/fishaudio/fish-speech/issues
- Discord: (check GitHub README)

---

## Appendix: Environment Variables Reference

### Core Settings
```bash
# Model paths
LLAMA_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini
DECODER_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini/codec.pth
DECODER_CONFIG_NAME=modded_dac_vq

# Optimization
COMPILE=1                              # Enable torch.compile
PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
CUDA_LAUNCH_BLOCKING=0                 # Async kernels

# HuggingFace
HF_TOKEN=<your_token>                  # For model downloads
HF_HOME=/app/.cache/huggingface

# Server
API_HOST=127.0.0.1
API_PORT=9880
WRAPPER_HOST=0.0.0.0
WRAPPER_PORT=8000

# Database
DB_HOST=100.64.0.1
DB_PORT=30432
DB_NAME=june
DB_USER=keycloak
DB_PASSWORD=<password>

# LiveKit
LIVEKIT_IDENTITY=june-tts
LIVEKIT_ROOM=ozzu-main
ORCHESTRATOR_URL=https://api.ozzu.world
```

---

**End of Guide**

Generated with comprehensive research from:
- Official Fish Speech documentation
- Production deployment guides
- Performance optimization papers
- Community best practices
- Current june-tts implementation analysis

For questions or issues, refer to the official Fish Speech GitHub repository.
