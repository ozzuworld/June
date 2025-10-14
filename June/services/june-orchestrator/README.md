# June Orchestrator v3.0 - LiveKit Integration

## Overview

The June Orchestrator has been completely refactored to integrate with **LiveKit** instead of Janus Gateway. This provides better scalability, modern WebRTC features, and seamless Kubernetes integration with STUNner.

## Key Changes

### ❌ **Removed (Janus Integration)**
- Janus Gateway dependencies
- Manual WebRTC session handling
- Janus admin API calls
- Complex room management logic

### ✅ **Added (LiveKit Integration)**
- LiveKit Python SDK integration
- Automatic room creation and management
- JWT-based access tokens
- Webhook-based event handling
- Participant management APIs
- Guest token generation

## Architecture

```
[ Client ] ↔️ [ STUNner ] ↔️ [ LiveKit ] ↔️ [ Orchestrator ]
                                     ↕️
                               [ TTS/STT Services ]
```

## API Endpoints

### Session Management
- `POST /api/sessions` - Create new session with LiveKit room
- `GET /api/sessions/{id}` - Get session info with access token
- `DELETE /api/sessions/{id}` - Delete session and cleanup room
- `GET /api/sessions/{id}/participants` - List room participants
- `DELETE /api/sessions/{id}/participants/{identity}` - Remove participant
- `POST /api/sessions/{id}/guest-token` - Generate guest access token

### LiveKit Webhooks
- `POST /api/livekit-webhooks` - Handle LiveKit events

### AI Integration
- `POST /api/ai/chat` - Process AI requests (unchanged)

## Environment Variables

```bash
# LiveKit Configuration
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
LIVEKIT_WS_URL=ws://livekit.livekit.svc.cluster.local:7880

# Service URLs (unchanged)
TTS_SERVICE_URL=http://june-tts.june-services.svc.cluster.local:8000
STT_SERVICE_URL=http://june-stt.june-services.svc.cluster.local:8080
GEMINI_API_KEY=your_gemini_api_key_here
```

## LiveKit Configuration

Ensure your LiveKit deployment is configured with:

1. **Webhook URL**: Point to `https://your-orchestrator/api/livekit-webhooks`
2. **API Keys**: Match the `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`
3. **STUNner Integration**: Configured for NAT traversal

## Session Flow

1. **Create Session**: `POST /api/sessions`
   - Creates LiveKit room
   - Generates access token
   - Returns session info with WebRTC credentials

2. **Client Connection**: 
   - Client uses access token to connect to LiveKit
   - STUNner handles NAT traversal
   - Audio/video streams established

3. **Event Processing**:
   - LiveKit sends webhooks to orchestrator
   - Audio tracks trigger STT processing
   - AI responses generate TTS audio

4. **Cleanup**:
   - Session deletion removes LiveKit room
   - All participants automatically disconnected

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

# Build Docker image
docker build -t june-orchestrator:v3.0 .
```

## Testing

```bash
# Create a session
curl -X POST http://localhost:8080/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test_user"}'

# Get session info
curl http://localhost:8080/api/sessions/{session_id}

# Generate guest token
curl -X POST http://localhost:8080/api/sessions/{session_id}/guest-token \
  -H "Content-Type: application/json" \
  -d '{"session_id": "{session_id}", "guest_name": "guest_user"}'
```

## Migration Notes

This is a **breaking change** from v2.x. Key differences:

- **No more Janus**: All Janus-specific code removed
- **New API responses**: Sessions now return LiveKit access tokens
- **Different webhooks**: LiveKit events instead of Janus events
- **Simplified deployment**: No need for Janus Gateway containers

## Troubleshooting

### Common Issues

1. **Connection failures**: Check `LIVEKIT_WS_URL` and network connectivity
2. **Token errors**: Verify `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`
3. **Webhook failures**: Ensure webhook signature verification
4. **STUNner issues**: Check UDP routes and gateway configuration

### Logs

```bash
# Check orchestrator logs
kubectl logs -f deployment/june-orchestrator -n june-services

# Check LiveKit logs  
kubectl logs -f deployment/livekit -n livekit

# Check STUNner logs
kubectl logs -f deployment/stunner-gateway -n stunner-system
```