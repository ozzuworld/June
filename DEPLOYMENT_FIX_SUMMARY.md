# Deployment Fix Summary - October 19, 2025

## Issues Resolved

### 1. STT Service Configuration Error ✅ FIXED
**Problem**: `june-stt` service crashing with error: `'Config' object has no attribute 'WHISPER_NUM_WORKERS'`

**Root Cause**: Missing Whisper performance configuration parameters in `config.py`

**Fix Applied**: Added missing configuration parameters to `June/services/june-stt/config.py`:
- `WHISPER_NUM_WORKERS`: Number of workers for Whisper processing (default: 1)
- `WHISPER_CPU_THREADS`: CPU threads for Whisper processing (default: 4)  
- `WHISPER_BEAM_SIZE`: Beam size for Whisper inference (default: 5)

### 2. LiveKit Token Endpoint 404 Errors ✅ FIXED
**Problem**: Services receiving 404 errors when requesting tokens from `/api/livekit/token`

**Root Cause**: Duplicate route prefix in orchestrator service causing endpoint to be registered at `/api/livekit/api/livekit/token` instead of `/api/livekit/token`

**Fix Applied**: Removed duplicate prefix from router registration in orchestrator main.py:
- Changed: `app.include_router(livekit_router, prefix="/api/livekit", tags=["LiveKit"])`
- To: `app.include_router(livekit_router, tags=["LiveKit"])`

### 3. STT Service CUDA Support ✅ FIXED
**Problem**: STT service failing with `Requested float16 compute type, but the target device or backend do not support efficient float16 computation`

**Root Cause**: STT Dockerfile using `python:3.10-slim` base image without CUDA support, while cluster has GPU available

**Fix Applied**: Updated STT Dockerfile to use CUDA-enabled base image:
- Changed from: `python:3.10-slim`
- To: `nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04` (multi-stage build)
- Added PyTorch with CUDA 11.8 support
- Set environment variables for GPU acceleration

## Files Modified

1. `June/services/june-stt/config.py` - Added missing Whisper config parameters
2. `June/services/june-orchestrator/app/main.py` - Fixed duplicate route prefix
3. `June/services/june-stt/Dockerfile` - Added CUDA support for GPU acceleration

## Deployment Steps

**IMPORTANT**: The Dockerfile changes require rebuilding the container images.

### 1. Pull Latest Changes
```bash
cd /home/user/June
git pull origin master
```

### 2. Force Rebuild STT Service (Required for CUDA fix)
```bash
# Delete current STT deployment to force image rebuild
kubectl delete deployment june-stt -n june-services

# Redeploy (this will pull/rebuild the new CUDA-enabled image)
kubectl apply -f k8s/june-stt-deployment.yaml  # or your deployment method
```

### 3. Restart Orchestrator (Required for route fix)
```bash
# Force restart orchestrator to load new routing code
kubectl delete pod -l app=june-orchestrator -n june-services
```

### 4. Restart TTS Service (should work now with fixed orchestrator)
```bash
kubectl delete pod -l app=june-tts -n june-services
```

### 5. Monitor Recovery
```bash
kubectl get pods -n june-services -w
```

## Verification Steps

### 1. Check Orchestrator Token Endpoint
```bash
# Wait for orchestrator to be running, then test:
kubectl exec -it deployment/june-orchestrator -n june-services -- \
  curl -X POST http://localhost:8080/api/livekit/token \
  -H "Content-Type: application/json" \
  -d '{"service_identity":"test"}'
```

### 2. Verify STT GPU Detection
```bash
# Check if STT service detects CUDA
kubectl logs deployment/june-stt -n june-services | grep -i cuda
```

### 3. Check All Service Logs
```bash
kubectl logs -f deployment/june-stt -n june-services
kubectl logs -f deployment/june-tts -n june-services  
kubectl logs -f deployment/june-orchestrator -n june-services
```

## Expected Results

After applying these fixes:
- ✅ **june-stt**: Should detect GPU and use CUDA acceleration with float16
- ✅ **june-tts**: Should connect to LiveKit without 404 token errors
- ✅ **june-orchestrator**: Should serve token endpoint at `/api/livekit/token`
- ✅ **All services**: Should reach Running status instead of CrashLoopBackOff
- 🚀 **Performance**: Faster Whisper processing with GPU acceleration

## Commit Information

- **STT Config Fix**: `8646b3c8f1965c42ce17d63caa15a7d381d4af8e`
- **Orchestrator Route Fix**: `89e898268de00403615d1706c40e0f237ccdb4f9`
- **STT CUDA Support**: `d1e8df1c9ed559126ccf56b5a4f8c9466c5ebecf`

All fixes are now available in the master branch and ready for deployment.