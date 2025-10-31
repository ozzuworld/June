# June TTS Service - XTTS v2 Compliant

**Version 3.0.0** - Enhanced text-to-speech service with full XTTS v2 compliance, multi-reference voice cloning, and robust real-time LiveKit integration.

## 🚀 Features

### XTTS v2 Compliance
- **Multi-reference voice cloning** for superior quality
- **17 language support** with validation
- **Model warmup** to reduce first-request latency
- **Synthesis timeout protection** (10s max)
- **Reference audio caching** and validation

### Real-time Performance
- **Decoupled synthesis pipeline** with asyncio.Queue
- **Monotonic timing** for consistent LiveKit publishing
- **Performance metrics** and observability
- **Background processing** to prevent blocking

### Voice Chat Optimizations
- **1500 character limit** for real-time responses
- **Streaming-friendly synthesis** with sentence splitting
- **Robust error handling** and recovery
- **Audio quality validation** and normalization

## 🌍 Supported Languages

XTTS v2 supports **17 languages** with automatic validation:

```
en (English)     es (Spanish)     fr (French)      de (German)
it (Italian)     pt (Portuguese)  pl (Polish)      tr (Turkish)
ru (Russian)     nl (Dutch)       cs (Czech)       ar (Arabic)
zh-cn (Chinese)  ja (Japanese)    hu (Hungarian)   ko (Korean)
hi (Hindi)
```

## 📡 API Endpoints

### Core Synthesis

#### `POST /synthesize`
Generate audio file from text

```json
{
  "text": "Hello, this is a voice cloning test.",
  "language": "en",
  "speaker_wav": [
    "https://example.com/reference1.wav",
    "/local/reference2.wav"
  ],
  "speed": 1.0
}
```

#### `POST /publish-to-room`
Synthesize and publish to LiveKit room

```json
{
  "text": "AI response for voice chat",
  "language": "en",
  "speaker_wav": "https://example.com/voice.wav",
  "speed": 1.1
}
```

**Response:**
```json
{
  "status": "success",
  "text_length": 28,
  "audio_size": 89344,
  "synthesis_time_ms": 1247.3,
  "language": "en",
  "speaker_references": 1,
  "message": "Audio being published to room"
}
```

### Monitoring & Debug

#### `GET /metrics`
Performance metrics and statistics

```json
{
  "synthesis_count": 45,
  "avg_synthesis_time_ms": 1205.67,
  "avg_publish_time_ms": 423.12,
  "cache_hit_rate": 0.73,
  "reference_cache_size": 12,
  "queue_size": 2
}
```

#### `GET /languages`
List supported languages

#### `GET /healthz`
Health check with system status

#### `GET /debug/audio-test`
Generate test tone to verify pipeline

## 🎤 Voice Cloning Best Practices

### Reference Audio Quality

**Optimal reference audio:**
- **Duration:** 6+ seconds (minimum 2 seconds)
- **Quality:** Clean, no background noise
- **Format:** WAV preferred, MP3 acceptable
- **Sample rate:** 16-48kHz (auto-normalized to 24kHz)
- **Channels:** Mono preferred (stereo auto-converted)

### Multi-Reference Cloning

For best voice cloning quality, provide multiple reference samples:

```json
{
  "text": "Your synthesized text here",
  "speaker_wav": [
    "https://example.com/sample1.wav",
    "https://example.com/sample2.wav",
    "https://example.com/sample3.wav"
  ]
}
```

**Or comma-separated:**
```json
{
  "speaker_wav": "ref1.wav,ref2.wav,ref3.wav"
}
```

### Language-Voice Matching

- Match reference voice language to synthesis language
- Cross-language cloning may produce mixed accents
- Service logs warnings for language mismatches

## 🏗️ Architecture

### Synthesis Pipeline

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   API Request   │───▶│  Synthesis Queue │───▶│   TTS Worker    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                          │
┌─────────────────┐    ┌──────────────────┐              │
│ LiveKit Publisher│◀───│  Audio Processing│◀─────────────┘
└─────────────────┘    └──────────────────┘
```

### Key Components

1. **Synthesis Worker** - Background processing with timeout protection
2. **Reference Cache** - URL/file caching with automatic cleanup
3. **Audio Processor** - Normalization and LiveKit format conversion
4. **Metrics Collector** - Performance tracking and observability

## 🚀 Deployment

### Docker Build

```bash
cd June/services/june-tts
docker build -t june-tts:3.0.0 .
```

### Environment Variables

```bash
# Core configuration
TTS_MODEL=tts_models/multilingual/multi-dataset/xtts_v2
LOG_LEVEL=INFO
PORT=8000

# LiveKit integration
LIVEKIT_WS_URL=ws://livekit-server:80
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret

# Orchestrator integration
ORCHESTRATO_URL=http://june-orchestrator:8080
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-tts
spec:
  replicas: 1
  selector:
    matchLabels:
      app: june-tts
  template:
    metadata:
      labels:
        app: june-tts
    spec:
      containers:
      - name: june-tts
        image: june-tts:3.0.0
        ports:
        - containerPort: 8000
        resources:
          requests:
            memory: "2Gi"
            cpu: "500m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
            nvidia.com/gpu: 1
        env:
        - name: TTS_MODEL
          value: "tts_models/multilingual/multi-dataset/xtts_v2"
        - name: LOG_LEVEL
          value: "INFO"
```

## 🔧 Configuration

### Performance Tuning

**For high-throughput:**
- Increase synthesis queue size: `maxsize=20`
- Add multiple synthesis workers
- Use GPU with sufficient VRAM (4GB+ recommended)

**For low-latency:**
- Pre-warm common voices on startup
- Use local reference files vs. remote URLs
- Reduce max text length for faster synthesis

### Resource Requirements

**Minimum:**
- RAM: 2GB
- GPU: 2GB VRAM (CUDA 11.8+)
- CPU: 2 cores

**Recommended:**
- RAM: 4GB
- GPU: 4GB+ VRAM
- CPU: 4 cores
- Storage: 10GB for model cache

## 🐛 Troubleshooting

### Common Issues

**"TTS model not ready"**
- Check GPU availability and CUDA version
- Verify model download completed
- Check available VRAM (htop/nvidia-smi)

**"Reference audio file not found"**
- Verify file paths are accessible
- Check URL accessibility and format
- Ensure audio duration > 2 seconds

**"Synthesis timeout"**
- Reduce text length (<1500 chars)
- Check GPU memory usage
- Monitor synthesis worker queue

**LiveKit connection issues**
- Verify orchestrator token endpoint
- Check network connectivity to LiveKit server
- Review LiveKit server logs

### Debug Commands

```bash
# Check service health
curl http://localhost:8000/healthz

# View performance metrics
curl http://localhost:8000/metrics

# Test audio pipeline
curl http://localhost:8000/debug/audio-test

# Check supported languages
curl http://localhost:8000/languages
```

### Logging

Key log messages to monitor:
- `🚀 Starting June TTS Service v3.0` - Startup
- `✅ TTS model initialized` - Model ready
- `🔥 Warming up TTS model` - Warmup process
- `✅ TTS connected to ozzu-main room` - LiveKit connected
- `🎤 Synthesizing (en): Hello world...` - Synthesis start
- `✅ Published 120/120 frames` - Successful publish

## 🔄 Migration from v2.x

### Breaking Changes

1. **speaker_wav now accepts arrays** for multi-reference cloning
2. **Language validation** - invalid languages default to "en"
3. **Text length limit** reduced to 1500 characters
4. **New response format** with detailed metrics

### Migration Steps

1. Update client code to handle new response format
2. Adapt to array-based speaker_wav (backward compatible)
3. Verify language codes against supported list
4. Update monitoring to use `/metrics` endpoint

## 📈 Performance Benchmarks

**Typical Performance (RTX 3060, 12GB):**
- Synthesis: 800-1500ms for 100-word text
- Publishing: 200-400ms for 3-second audio
- Memory: 2-3GB RAM, 4-6GB VRAM
- Throughput: 4-6 requests/minute sustained

**Optimized Performance (RTX 4090):**
- Synthesis: 400-800ms for 100-word text
- Publishing: 150-250ms for 3-second audio
- Throughput: 8-12 requests/minute sustained

## 🤝 Contributing

When contributing to june-tts:

1. **Test voice cloning quality** with various reference samples
2. **Verify language support** across all 17 languages
3. **Check real-time performance** under load
4. **Validate LiveKit integration** end-to-end
5. **Update documentation** for any API changes

## 📜 License

By using this service, you agree to the [Coqui TTS License](https://github.com/coqui-ai/TTS/blob/dev/LICENSE.txt).

---

**June TTS v3.0.0** - Built for production voice chat with XTTS v2 excellence.