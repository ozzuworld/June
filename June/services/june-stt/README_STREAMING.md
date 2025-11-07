# June STT - Whisper-Streaming Edition

## 🚀 Quick Start

```bash
# Build
cd June/services/june-stt
docker build -t june-stt:streaming .

# Run
docker run --gpus all -p 8001:8001 \
  -e LIVEKIT_WS_URL=ws://livekit:80 \
  -e ORCHESTRATOR_URL=http://orchestrator:8080 \
  june-stt:streaming

# Test
curl http://localhost:8001/healthz
```

## 🎯 Performance

| Metric | Before (WhisperX) | After (Whisper-Streaming) |
|--------|------------------|---------------------------|
| **Latency** | 15-18 seconds | **3.3-4 seconds** |
| **Improvement** | - | **78% faster** |

## 📚 Documentation

See [WHISPER_STREAMING_MIGRATION.md](./WHISPER_STREAMING_MIGRATION.md) for:
- Complete architecture explanation
- Problem analysis
- Implementation details
- Troubleshooting guide
- Performance comparison

## 🔑 Key Features

- ✅ **Real-time streaming** (not batch processing)
- ✅ **LocalAgreement-2 policy** (low latency + high quality)
- ✅ **Silero VAD** (real-time voice activity detection)
- ✅ **Per-participant processors** (isolated state)
- ✅ **No audio buffering** (instant processing)
- ✅ **Faster-whisper backend** (GPU optimized)

## 🔧 Files Changed

### New Files
- `whisper_streaming_service.py` - Service wrapper
- `main_streaming.py` - Real-time implementation
- `WHISPER_STREAMING_MIGRATION.md` - Full documentation

### Updated Files
- `requirements.txt` - Whisper-streaming dependencies
- `Dockerfile` - Install from GitHub + new entrypoint

### Preserved (No Changes)
- `config.py` - Configuration system
- `livekit_token.py` - Authentication
- `streaming_utils.py` - Metrics

## ⚙️ Environment Variables

```bash
# Model
WHISPER_MODEL=large-v3-turbo
DEFAULT_LANGUAGE=en

# Streaming
MIN_CHUNK_SIZE=1.0
BUFFER_TRIMMING_SEC=15.0

# LiveKit
LIVEKIT_WS_URL=ws://livekit:80
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret

# Orchestrator
ORCHESTRATOR_URL=http://june-orchestrator:8080
```

## 📊 Monitoring

### Logs to Watch For

**✅ Success:**
```
🚀 June STT Service - Whisper-Streaming Edition
✅ Whisper-Streaming ready
✅ STT connected to LiveKit
🎤 First frame: ozzu-app | in_sr=48000 out_sr=16000
🎯 Confirmed: ozzu-app -> 'Good morning Jim.'
✅ Transcript sent: 'Good morning Jim.' [18 chars]
```

**❌ Old System (15s delay):**
```
[UTT] start pid=ozzu-app
[UTT] end pid=ozzu-app dur=15.01s  # Too slow!
[FINAL] calling WhisperX
```

### Health Check

```bash
curl http://localhost:8001/healthz | jq
```

```json
{
  "status": "healthy",
  "version": "9.0.0-whisper-streaming",
  "framework": "whisper-streaming (UFAL)",
  "features": {
    "real_time_streaming": true,
    "vad": "silero",
    "policy": "LocalAgreement-2",
    "expected_latency_sec": 3.3
  }
}
```

## 🐛 Troubleshooting

### "Module whisper_streaming not found"

```bash
# Verify installation in Dockerfile:
RUN pip install --no-cache-dir git+https://github.com/ufal/whisper_streaming
```

### High latency (>5s)

```bash
# Check GPU
nvidia-smi

# Try smaller model
WHISPER_MODEL=base.en
```

### No transcripts

```bash
# Check logs for processor creation
kubectl logs -f deployment/june-stt | grep "Created streaming processor"
```

## 🔗 References

- [Whisper-Streaming Paper](https://aclanthology.org/2023.ijcnlp-demo.3) (IJCNLP-AACL 2023)
- [GitHub Repository](https://github.com/ufal/whisper_streaming) (3.4k stars)
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) (Backend)

## 🔄 Rollback

```bash
# Revert to WhisperX
kubectl set image deployment/june-stt \
  june-stt=ozzuworld/june-stt:whisperx-latest
```

## ✅ Deploy to Production

```bash
# 1. Build and push
docker build -t ozzuworld/june-stt:streaming .
docker push ozzuworld/june-stt:streaming

# 2. Update Kubernetes
kubectl set image deployment/june-stt \
  june-stt=ozzuworld/june-stt:streaming \
  -n june-services

# 3. Monitor
kubectl logs -f deployment/june-stt -n june-services
```

---

**🎯 Recommendation:** Deploy immediately. The 78% latency reduction is critical for user experience.
