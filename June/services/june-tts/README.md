# June TTS Service - Orpheus Edition

**Production-ready Text-to-Speech service powered by Orpheus TTS**

## Quick Start

### Using Docker

```bash
docker-compose build june-tts
docker-compose up -d june-tts
docker-compose logs -f june-tts
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ORPHEUS_MODEL` | `canopylabs/orpheus-3b-0.1-ft` | Model to use |
| `VLLM_GPU_MEMORY_UTILIZATION` | `0.5` | GPU memory fraction (0.0-1.0) |
| `WARMUP_ON_STARTUP` | `0` | Pre-warm model on startup |
| `MAX_WORKERS` | `2` | Thread pool workers |
| `DEVICE` | `cuda` | Device (cuda/cpu) |

**Important:** Set `VLLM_GPU_MEMORY_UTILIZATION` based on your available GPU memory.
For 11.6 GB GPUs with other services running, use `0.5` or lower.

## Architecture

- **Model:** Orpheus TTS (Llama-3b backbone)
- **Backend:** vLLM (AsyncLLMEngine)
- **Audio:** 24kHz native, resampled to 48kHz for LiveKit
- **Latency:** 100-200ms streaming
- **Voices:** 8 preset English voices (tara, leah, jess, leo, dan, mia, zac, zoe)

## API Endpoints

### Synthesize Speech
```bash
POST /api/tts/synthesize
{
  "text": "Hello world!",
  "room_name": "ozzu-main",
  "voice_id": "default",
  "language": "en",
  "temperature": 0.7,
  "repetition_penalty": 1.1
}
```

### Health Check
```bash
GET /health
```

### Voice Management
```bash
# List voices
GET /api/voices

# Clone voice
POST /api/voices/clone
FormData:
  - voice_id: unique_id
  - voice_name: Display Name
  - file: audio.wav (10-30 seconds, 24kHz recommended)
```

## GPU Memory Issues

If you see: `ValueError: Free memory on device is less than desired GPU memory utilization`

**Solutions:**
1. Lower `VLLM_GPU_MEMORY_UTILIZATION` (try 0.4 or 0.3)
2. Check other GPU processes: `nvidia-smi`
3. Restart services to free memory

## Troubleshooting

**No audio generated:**
- Check logs for errors during model initialization
- Verify GPU memory is sufficient
- Test with shorter text first

**High latency:**
- Increase `VLLM_GPU_MEMORY_UTILIZATION` if memory available
- Check GPU utilization with `nvidia-smi`

**Model download slow:**
- First startup downloads ~3-4GB model
- Set `HF_TOKEN` environment variable for faster downloads from HuggingFace

## Documentation

- [BUILD_ORPHEUS.md](BUILD_ORPHEUS.md) - Detailed build instructions
- [ORPHEUS_README.md](ORPHEUS_README.md) - Orpheus TTS overview
- [ORPHEUS_MIGRATION.md](ORPHEUS_MIGRATION.md) - Migration history and decisions
- [archive/](archive/) - Legacy migration docs (archived)

## Current Status

✅ Production-ready Orpheus TTS implementation
✅ GPU memory configuration fixed
✅ Legacy code removed
✅ Single consolidated codebase

---

**Last Updated:** 2025-11-18
**Version:** 8.0.0-orpheus (consolidated)
