# Frontend API Fix - External Calls

## Issue
Frontend was calling the wrong domain for orchestrator API endpoints.

## Solution
The orchestrator is exposed on a separate host via Ingress routing.

### Correct API Endpoints

**Orchestrator API (Token generation, etc.):**
```
https://api.ozzu.world/api/livekit/token
```

**LiveKit Server (WebRTC connection):**
```
https://livekit.ozzu.world/
```

**STT Service:**
```
https://stt.ozzu.world/
```

**TTS Service:**
```
https://tts.ozzu.world/
```

### Frontend Code Fix

**Before (incorrect):**
```javascript
fetch('https://livekit.ozzu.world/api/livekit/token', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ service_identity: 'frontend-user' })
})
```

**After (correct):**
```javascript
fetch('https://api.ozzu.world/api/livekit/token', {
  method: 'POST', 
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ service_identity: 'frontend-user' })
})
```

### Ingress Configuration

Your Helm template correctly routes by host:
- `api.ozzu.world` → `june-orchestrator:8080`
- `livekit.ozzu.world` → `livekit-backend:80`

No Ingress changes needed - just update frontend to use correct domain.

### Testing

```bash
# Test orchestrator token endpoint
curl -X POST https://api.ozzu.world/api/livekit/token \
  -H "Content-Type: application/json" \
  -d '{"service_identity":"test"}'

# Should return 200 with token
```