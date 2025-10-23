# Troubleshooting June Services

This guide covers common issues with `june-stt` and `june-tts` service failures in the multi-GPU container.

## Common Service Failure Patterns

### 1. Exit Status 1 with Supervisor Fatal State

**Symptoms:**
```
INFO exited: june-tts (exit status 1; not expected)
INFO exited: june-stt (exit status 1; not expected)
INFO gave up: june-tts entered FATAL state, too many start retries too quickly
```

**Debugging Steps:**

1. **Check detailed service logs:**
   ```bash
   # Inside the container
   tail -f /var/log/supervisor/june-stt-stdout.log
   tail -f /var/log/supervisor/june-stt-stderr.log
   tail -f /var/log/supervisor/june-tts-stdout.log
   tail -f /var/log/supervisor/june-tts-stderr.log
   ```

2. **Run services manually for diagnosis:**
   ```bash
   # Test STT service directly
   cd /app/stt
   python main.py
   
   # Test TTS service directly
   cd /app/tts
   python main.py
   ```

3. **Check Python import errors:**
   ```bash
   python -c "import fastapi; print('FastAPI OK')"
   python -c "import torch; print('PyTorch OK')"
   python -c "import faster_whisper; print('Whisper OK')"
   python -c "from TTS.api import TTS; print('TTS OK')"
   ```

### 2. Model Loading Issues

**Common Causes:**
- Missing GPU access (`CUDA_VISIBLE_DEVICES` not set)
- Insufficient GPU memory
- Model cache directory permissions
- Network issues downloading models

**Solutions:**
```bash
# Check GPU access
nvidia-smi
echo $CUDA_VISIBLE_DEVICES

# Check model directories
ls -la /app/models
ls -la /app/cache

# Test model loading manually
python -c "from faster_whisper import WhisperModel; model = WhisperModel('base')"
python -c "from TTS.api import TTS; tts = TTS('tts_models/multilingual/multi-dataset/xtts_v2')"
```

### 3. Port Binding Issues

**Symptoms:**
- Services start but health checks fail
- `curl: connection refused` on service ports

**Debug:**
```bash
# Check what's listening on service ports
netstat -tlpn | grep -E ':(8000|8001)'

# Test service endpoints
curl -f http://localhost:8000/healthz
curl -f http://localhost:8001/healthz
```

### 4. Dependency Conflicts

**Common Issues:**
- NumPy version incompatibility
- PyTorch CUDA version mismatch
- Package version conflicts

**Verification:**
```bash
# Check package versions
pip list | grep -E '(torch|numpy|faster-whisper|TTS)'

# Verify CUDA compatibility
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
python -c "import torch; print(f'CUDA version: {torch.version.cuda}')"
```

## Service-Specific Issues

### STT Service (june-stt)

**Critical Dependencies:**
- `faster-whisper`
- `torch` with CUDA support
- Audio processing libraries

**Common Failures:**
```python
# Test Whisper model loading
from faster_whisper import WhisperModel
model = WhisperModel("base", device="cuda", compute_type="float16")
```

### TTS Service (june-tts)

**Critical Dependencies:**
- `TTS` (Coqui TTS)
- `torch` with CUDA support
- Speaker embedding models

**Common Failures:**
```python
# Test TTS initialization
from TTS.api import TTS
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")
```

## Resolution Checklist

1. **Environment Variables:**
   - [ ] `STT_PORT=8001` and `TTS_PORT=8000` set
   - [ ] `CUDA_VISIBLE_DEVICES=0` (or appropriate GPU ID)
   - [ ] `PYTHONPATH=/app:/app/stt:/app/tts`
   - [ ] Model cache paths configured

2. **File Permissions:**
   - [ ] `/app` directory owned by `juneuser`
   - [ ] Model and cache directories writable
   - [ ] Service scripts executable

3. **System Resources:**
   - [ ] Sufficient GPU memory available
   - [ ] Disk space for model downloads
   - [ ] Network connectivity for initial model downloads

4. **Service Configuration:**
   - [ ] Supervisor config valid
   - [ ] Service entry points correct
   - [ ] Health check endpoints responding

## Emergency Debugging

If services continue to fail, run the container interactively:

```bash
docker run -it --gpus all --rm june-gpu-multi /bin/bash

# Skip supervisor, run services manually
cd /app/stt && python main.py &
cd /app/tts && python main.py &

# Check logs in real-time
tail -f /var/log/supervisor/*.log
```

## Getting Help

When reporting issues, include:
1. Complete service logs from `/var/log/supervisor/`
2. Output of manual service runs
3. GPU and system information (`nvidia-smi`, `lscpu`)
4. Environment variables (`env | grep -E '(STT|TTS|CUDA|PYTHON)'`)
