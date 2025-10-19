# Deployment Fix Summary - October 19, 2025

## Issues Resolved

### 1. STT Service Configuration Error
**Problem**: `june-stt` service crashing with error: `'Config' object has no attribute 'WHISPER_NUM_WORKERS'`

**Root Cause**: Missing Whisper performance configuration parameters in `config.py`

**Fix Applied**: Added missing configuration parameters to `June/services/june-stt/config.py`:
- `WHISPER_NUM_WORKERS`: Number of workers for Whisper processing (default: 1)
- `WHISPER_CPU_THREADS`: CPU threads for Whisper processing (default: 4)  
- `WHISPER_BEAM_SIZE`: Beam size for Whisper inference (default: 5)

**Files Modified**:
- `June/services/june-stt/config.py`

### 2. LiveKit Token Endpoint 404 Errors
**Problem**: Services receiving 404 errors when requesting tokens from `/api/livekit/token`

**Root Cause**: Duplicate route prefix in orchestrator service causing endpoint to be registered at `/api/livekit/api/livekit/token` instead of `/api/livekit/token`

**Fix Applied**: Removed duplicate prefix from router registration in orchestrator main.py:
- Changed: `app.include_router(livekit_router, prefix="/api/livekit", tags=["LiveKit"])`
- To: `app.include_router(livekit_router, tags=["LiveKit"])`

**Files Modified**:
- `June/services/june-orchestrator/app/main.py`

## Verification Steps

1. **Check Token Endpoint**: 
   ```bash
   kubectl exec -it deployment/june-orchestrator -n june-services -- curl http://localhost:8080/api/livekit/token
   ```

2. **Restart Services**:
   ```bash
   kubectl delete pod -l app=june-stt -n june-services
   kubectl delete pod -l app=june-tts -n june-services
   kubectl delete pod -l app=june-orchestrator -n june-services
   ```

3. **Monitor Pod Status**:
   ```bash
   kubectl get pods -n june-services -w
   ```

4. **Check Service Logs**:
   ```bash
   kubectl logs -f deployment/june-stt -n june-services
   kubectl logs -f deployment/june-tts -n june-services
   kubectl logs -f deployment/june-orchestrator -n june-services
   ```

## Expected Results

After applying these fixes:
- ✅ STT service should initialize Whisper model without configuration errors
- ✅ All services should successfully obtain LiveKit tokens from orchestrator
- ✅ Services should connect to LiveKit room and be ready for audio processing
- ✅ No more CrashLoopBackOff status for june-stt and june-tts pods

## Commit Information

- **STT Config Fix**: `8646b3c8f1965c42ce17d63caa15a7d381d4af8e`
- **Orchestrator Route Fix**: `89e898268de00403615d1706c40e0f237ccdb4f9`

Both fixes are now available in the master branch and ready for deployment.