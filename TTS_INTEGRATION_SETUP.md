# June TTS Integration Setup Guide

🎵 This guide shows you how to set up the orchestrator-TTS communication for voice responses.

## 🏗️ Architecture Overview

```
┌─────────────────┐    HTTPS API     ┌─────────────────┐
│  June           │ ───────────────→ │  June           │
│  Orchestrator   │                  │  TTS            │
│                 │ ←─────────────── │                 │
│ • AI Responses  │   Audio Data     │ • OpenVoice     │
│ • Conversation  │                  │ • Voice Cloning │
│ • Auth          │                  │ • Standard TTS  │
└─────────────────┘                  └─────────────────┘
        ↕ JSON + Audio
┌─────────────────┐
│  June Voice     │
│  Frontend       │
│                 │
│ • React Native  │
│ • Audio Player  │
│ • Voice Input   │
└─────────────────┘
```

## 🚀 What's Been Added

### 1. **TTS Service Enhancements**
- ✅ **New Standard TTS Endpoint**: `/v1/tts` (compatible with orchestrator)
- ✅ **Health Check Integration**: Proper status monitoring
- ✅ **Voice Management**: `/v1/voices` endpoint
- ✅ **Existing Voice Cloning**: Still works via `/clone/voice`

### 2. **Orchestrator Enhancements**
- ✅ **TTS Service Integration**: `tts_service.py` with caching and fallback
- ✅ **Enhanced Conversation Manager**: Automatic audio generation
- ✅ **New Chat Endpoints**: Audio-enabled responses
- ✅ **Voice Cloning Support**: Reference audio to speech

### 3. **New API Endpoints**

#### Standard Chat with Audio:
```bash
POST /v1/chat
{
  "text": "Hello, how are you?",
  "include_audio": true,
  "voice_id": "default",
  "speed": 1.0
}

# Response includes both text and base64 audio
{
  "ok": true,
  "message": {
    "text": "Hi! I'm doing great, thanks for asking!",
    "role": "assistant"
  },
  "audio": {
    "data": "UklGRj4IAABXQVZF..." // base64 audio
    "content_type": "audio/wav",
    "size_bytes": 45230
  }
}
```

#### Voice Cloning:
```bash
POST /v1/chat/clone
{
  "text": "This is my cloned voice speaking",
  "reference_audio_b64": "UklGRj4IAABXQVZF..." // your voice sample
}
```

## ⚙️ Configuration

### Environment Variables

#### **June Orchestrator** (.env):
```bash
# TTS Service Configuration
EXTERNAL_TTS_URL=http://localhost:8001  # Your TTS service URL

# TTS Behavior
TTS_ENABLE_CACHING=true
TTS_ENABLE_FALLBACK=true
TTS_DEFAULT_VOICE=default
TTS_DEFAULT_SPEED=1.0
TTS_DEFAULT_LANGUAGE=EN

# Existing config...
KEYCLOAK_URL=your_keycloak_url
GEMINI_API_KEY=your_gemini_key
# etc...
```

#### **June TTS** (.env):
```bash
# OpenVoice Configuration (your existing setup)
OPENVOICE_CHECKPOINTS_V2=/path/to/checkpoints
MELO_LANGUAGE=EN
CUDA_VISIBLE_DEVICES=0

# Optional: Default reference audio for standard TTS
DEFAULT_REFERENCE_AUDIO=/path/to/default_voice.wav

# CORS (allow orchestrator)
CORS_ALLOW_ORIGINS=http://localhost:8000,http://orchestator-url
```

## 🔧 Installation Steps

### 1. **Update TTS Service**

The new `standard_tts.py` router has been added. Update your TTS startup:

```python
# In June/services/june-tts/app/main.py (already updated)
# The new standard_tts router is now included
```

### 2. **Update Orchestrator Service**

New files added:
- `tts_service.py` - TTS integration layer
- `enhanced_conversation_manager.py` - Audio-enabled conversations
- `enhanced_conversation_routes.py` - New API endpoints

### 3. **Test the Integration**

#### Start Both Services:
```bash
# Terminal 1: Start TTS Service
cd June/services/june-tts
python -m app.main
# Should run on http://localhost:8001

# Terminal 2: Start Orchestrator
cd June/services/june-orchestrator  
python app.py
# Should run on http://localhost:8000
```

#### Test TTS Health:
```bash
curl http://localhost:8001/healthz
curl http://localhost:8001/v1/status
curl http://localhost:8001/v1/voices
```

#### Test Orchestrator Integration:
```bash
curl http://localhost:8000/v1/tts/status
```

#### Test End-to-End Chat:
```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "text": "Hello, can you speak to me?",
    "include_audio": true
  }'
```

## 🎯 Integration Flow

Here's what happens when a user sends a message:

1. **User sends text** → Orchestrator `/v1/chat`
2. **Orchestrator processes** → AI generates text response  
3. **Orchestrator calls TTS** → `POST /v1/tts` with AI text
4. **TTS generates audio** → Returns WAV bytes
5. **Orchestrator combines** → Returns JSON with text + base64 audio
6. **Frontend plays audio** → User hears the response

## 🔍 Troubleshooting

### Common Issues:

**TTS Service Not Found:**
```bash
# Check TTS service is running
curl http://localhost:8001/healthz

# Check orchestrator can reach it
curl http://localhost:8000/v1/tts/status
```

**Audio Generation Fails:**
- Check `OPENVOICE_CHECKPOINTS_V2` path exists
- Verify CUDA/GPU availability if using GPU
- Check logs for OpenVoice initialization errors

**No Default Reference Audio:**
- Set `DEFAULT_REFERENCE_AUDIO` environment variable
- Or let the system create a synthetic default

**Memory Issues:**
- Reduce `TTS_CACHE_SIZE` if memory is limited
- Set `TTS_ENABLE_CACHING=false` to disable caching

### Debug Endpoints:

```bash
# Orchestrator debug
curl http://localhost:8000/debug/env
curl http://localhost:8000/v1/tts/status

# TTS debug
curl http://localhost:8001/v1/status
curl http://localhost:8001/voices/test?id=0
```

## 📱 Frontend Integration

Update your React Native app to handle audio responses:

```javascript
// In your june-voice-clean app
const response = await fetch('/v1/chat', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    text: userMessage,
    include_audio: true
  })
});

const data = await response.json();

// Display text
setMessages(prev => [...prev, data.message]);

// Play audio if available
if (data.audio) {
  const audioUri = `data:audio/wav;base64,${data.audio.data}`;
  await Audio.Sound.createAsync({ uri: audioUri });
  // Play the sound...
}
```

## 🎉 Next Steps

1. **Test the integration** with both services running
2. **Update your frontend** to handle audio responses
3. **Configure voice preferences** per user
4. **Add voice cloning** for personalized responses
5. **Monitor performance** and adjust TTS caching as needed

---

🎵 **Your AI assistant can now speak!** 🎵

When users send messages, they'll get both text and audio responses automatically. The TTS integration is designed to be robust with caching, fallbacks, and health monitoring.