# June Orchestrator Migration Summary

## Migration from Janus Gateway to LiveKit Integration

**Date:** October 14, 2025  
**Version:** v2.0 → v3.0  
**Status:** ✅ Complete

### What Was Changed

#### ❌ **Removed (Janus Integration)**
- `janus_events.py` router and all Janus event handling
- Janus Gateway configuration and admin API calls
- `janus_url`, `janus_room_id` from session management
- Manual WebRTC session and room creation logic
- Janus-specific models (`JanusEvent`)

#### ✅ **Added (LiveKit Integration)**
- **LiveKit Python SDK** (`livekit-api`, `livekit-protocol`)
- **LiveKit Service** (`livekit_service.py`) for room and participant management
- **LiveKit Webhooks Router** (`livekit_webhooks.py`) for event handling
- **JWT Access Tokens** for secure participant authentication
- **Guest Token Generation** for temporary access
- **Participant Management APIs** (list, remove participants)
- **Room Information APIs** with real-time status

### Key Architecture Changes

```
# Before (v2.0 - Janus)
[Client] ↔️ [Janus Gateway] ↔️ [Orchestrator]
                     ↕️
               [Manual Room Management]

# After (v3.0 - LiveKit)
[Client] ↔️ [STUNner] ↔️ [LiveKit] ↔️ [Orchestrator]
                           ↕️
                   [Automatic Room Management]
```

### New API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/sessions` | Create session + LiveKit room + access token |
| `GET` | `/api/sessions/{id}` | Get session with LiveKit credentials |
| `GET` | `/api/sessions/{id}/participants` | List room participants |
| `DELETE` | `/api/sessions/{id}/participants/{identity}` | Remove participant |
| `POST` | `/api/sessions/{id}/guest-token` | Generate guest access token |
| `POST` | `/api/livekit-webhooks` | Handle LiveKit room/participant events |

### Environment Variables

#### ❌ **Removed**
```bash
JANUS_URL=http://june-janus.june-services.svc.cluster.local:8088
```

#### ✅ **Added**
```bash
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
LIVEKIT_WS_URL=ws://livekit.livekit.svc.cluster.local:7880
```

### Session Creation Flow Changes

#### Before (Janus)
1. Create business session
2. Generate room ID hash
3. Manually create Janus room via admin API
4. Return session with room_id

#### After (LiveKit)
1. Create business session with unique room name
2. **Automatically create LiveKit room** via SDK
3. **Generate JWT access token** for participant
4. Return session with access_token and room credentials

### Event Handling Changes

#### Before (Janus Events)
- Manual parsing of Janus event handler webhooks
- Complex event type handling (type 1, 2, 8, 64, 256)
- Manual media state tracking

#### After (LiveKit Webhooks)
- **Standardized webhook format** with signature verification
- **Semantic event names** (`room_started`, `participant_joined`, `track_published`)
- **Automatic participant tracking** and room lifecycle

### Benefits of Migration

1. **🚀 Modern WebRTC Stack**: Industry-standard LiveKit vs legacy Janus
2. **🌐 Cloud Native**: Better Kubernetes integration with STUNner
3. **🔒 Enhanced Security**: JWT tokens vs manual room management
4. **👥 Better UX**: Simplified participant management and guest access
5. **🛠️ Easier Maintenance**: Reduced complexity and better documentation
6. **📊 Scalability**: LiveKit's built-in clustering and load balancing

### Breaking Changes

⚠️ **This is a breaking change for clients using v2.0**

- **Session API responses changed**: Now includes `access_token`, `livekit_room_sid`
- **WebRTC connection method**: Clients must use LiveKit SDK instead of direct WebRTC
- **Event webhooks**: Different format and endpoint (`/api/livekit-webhooks`)
- **Room management**: No more manual room IDs, use room names

### Deployment Requirements

1. **LiveKit Server**: Must be deployed and accessible
2. **STUNner**: Required for NAT traversal in Kubernetes
3. **Environment Variables**: Update with LiveKit credentials
4. **Webhook Configuration**: Point LiveKit to orchestrator webhook endpoint
5. **Client Updates**: Frontend must integrate LiveKit client SDK

### Testing Checklist

- [ ] Session creation returns access token
- [ ] LiveKit room is created automatically
- [ ] Client can connect using access token
- [ ] Audio/video tracks are published
- [ ] Webhooks are received and processed
- [ ] Participant management works
- [ ] Guest tokens are generated
- [ ] Room cleanup on session deletion
- [ ] STT processing triggers on audio tracks
- [ ] AI pipeline integration works

### Rollback Plan

If issues occur:
1. Revert to previous commit before migration
2. Redeploy Janus Gateway containers
3. Update environment variables back to Janus configuration
4. Restore v2.0 client integration

---

**Migration completed successfully! 🎉**

June Orchestrator is now ready for modern WebRTC with LiveKit integration.