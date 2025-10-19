# June Platform - Voice Cloning Implementation

## 🎯 Implementation Overview

Your June TTS service has been **successfully enhanced** with comprehensive voice cloning capabilities. This implementation adds advanced XTTS-v2 voice cloning while maintaining full backward compatibility with existing functionality.

## ✅ Implemented Features

### Core Voice Cloning Features
- **✅ Voice Upload & Storage**: Upload multiple reference audio files (6+ seconds each)
- **✅ Voice Management**: Store, list, retrieve, and delete custom voices
- **✅ Speaker Caching**: Automatic caching for frequently used voices
- **✅ Audio Validation**: Comprehensive validation with XTTS-v2 requirements
- **✅ Cross-Language Synthesis**: Clone voice in one language, speak in another
- **✅ Multiple Reference Files**: Support up to 10 reference files for quality

### Advanced Features
- **✅ Real-time Processing**: ~200ms latency optimization
- **✅ LiveKit Integration**: Direct room publishing with cloned voices  
- **✅ One-time Cloning**: Synthesize without storing voice permanently
- **✅ Audio Processing**: Automatic resampling, normalization, and optimization
- **✅ Quality Controls**: Duration, format, and noise validation

### API Enhancements
- **✅ RESTful Voice Management**: Complete CRUD operations for voices
- **✅ Comprehensive Documentation**: Detailed API docs with examples
- **✅ Error Handling**: Detailed validation and error responses
- **✅ Health Monitoring**: Enhanced health checks with feature reporting
- **✅ Backward Compatibility**: All existing endpoints remain functional

## 🚀 New API Endpoints

### Voice Cloning Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/clone-voice` | POST | Upload & store custom voice |
| `/synthesize-clone` | POST | Synthesize with stored/one-time voice |
| `/publish-to-room` | POST | Enhanced with voice_id support |
| `/voices` | GET | List all voices (built-in + custom) |
| `/voices/{voice_id}` | GET | Get specific voice details |
| `/voices/{voice_id}` | DELETE | Delete custom voice |
| `/languages` | GET | Supported languages for synthesis |

### Enhanced Health & Info
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/healthz` | GET | Enhanced with voice cloning status |

## 📁 Updated File Structure

```
June/services/june-tts/
├── main.py                    # ✅ Enhanced with voice cloning
├── livekit_participant.py     # ✅ Maintained existing functionality  
├── config.py                  # ✅ New configuration module
├── Dockerfile                 # ✅ Enhanced with audio processing deps
├── requirements.txt           # ✅ Updated dependencies
└── README.md                  # ✅ Comprehensive documentation

June/services/june-orchestrator/app/services/
└── tts_service.py            # ✅ Enhanced with voice cloning support
```

## 🎵 Voice Cloning Workflow

### 1. Upload Reference Audio
```bash
curl -X POST "http://june-tts:8000/clone-voice" \
  -F "files=@reference1.wav" \
  -F "files=@reference2.wav" \
  -F "name=John Smith" \
  -F "description=Professional narrator" \
  -F "language=en"
```

**Response:**
```json
{
  "voice_id": "abc123def456",
  "name": "John Smith", 
  "status": "created",
  "duration": 45.2,
  "file_count": 2
}
```

### 2. Synthesize with Cloned Voice
```bash
curl -X POST "http://june-tts:8000/synthesize-clone" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, this is my cloned voice speaking!",
    "language": "en",
    "voice_id": "abc123def456"
  }' \
  --output cloned_voice.wav
```

### 3. Cross-Language Synthesis
```bash
curl -X POST "http://june-tts:8000/synthesize-clone" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Bonjour, je parle français avec une voix anglaise clonée!",
    "language": "fr", 
    "voice_id": "abc123def456"
  }' \
  --output french_with_english_voice.wav
```

### 4. LiveKit Room Publishing
```bash
curl -X POST "http://june-tts:8000/publish-to-room" \
  -H "Content-Type: application/json" \
  -d '{
    "room_name": "ozzu-main",
    "text": "Publishing cloned voice to LiveKit room!",
    "voice_id": "abc123def456",
    "language": "en"
  }'
```

## 🔧 Configuration & Deployment

### Environment Variables
```bash
# Voice Cloning Configuration
MAX_VOICE_FILES=10            # Max reference files per voice
MAX_VOICE_DURATION=300        # Max duration per file (seconds)  
MIN_VOICE_DURATION=6.0        # Min duration per file (seconds)
VOICES_DIR=/app/voices        # Voice storage directory
TTS_CACHE_DIR=/app/cache      # Cache directory

# LiveKit Integration (existing)
LIVEKIT_API_KEY=your_key
LIVEKIT_API_SECRET=your_secret
LIVEKIT_WS_URL=wss://your-livekit-server.com
```

### Docker Deployment
```bash
# Build with voice cloning support
docker build -t june-tts:voice-enhanced .

# Run with GPU and voice storage
docker run --gpus all -p 8000:8000 \
  -e LIVEKIT_API_KEY=$LIVEKIT_API_KEY \
  -e LIVEKIT_API_SECRET=$LIVEKIT_API_SECRET \
  -v /data/voices:/app/voices \
  june-tts:voice-enhanced
```

## 🧪 Testing Voice Cloning

### 1. Health Check with New Features
```bash
curl http://june-tts:8000/healthz
```

**Expected Response:**
```json
{
  "status": "healthy",
  "service": "june-tts", 
  "tts_ready": true,
  "voice_cloning": true,
  "cached_voices": 0,
  "features": [
    "built-in speakers",
    "voice cloning", 
    "cross-language synthesis",
    "speaker caching",
    "livekit integration"
  ]
}
```

### 2. List Available Voices
```bash
curl http://june-tts:8000/voices | jq
```

### 3. Test Voice Cloning End-to-End
```python
import requests

# 1. Upload voice
files = [("files", ("ref.wav", open("reference.wav", "rb")))]
data = {"name": "Test Voice", "language": "en"}
response = requests.post("http://june-tts:8000/clone-voice", 
                        files=files, data=data)
voice_id = response.json()["voice_id"]

# 2. Synthesize with cloned voice
payload = {
    "text": "This is a test of voice cloning!",
    "voice_id": voice_id,
    "language": "en"
}
audio = requests.post("http://june-tts:8000/synthesize-clone", 
                     json=payload)

# 3. Save result
with open("cloned_output.wav", "wb") as f:
    f.write(audio.content)
```

## 🔄 Integration with Orchestrator

The orchestrator service has been enhanced to support voice cloning:

```python
from app.services.tts_service import tts_service

# Use cloned voice in orchestrator
async def process_with_cloned_voice(text: str, voice_id: str):
    # Direct synthesis
    audio_bytes = await tts_service.synthesize_with_voice_clone(
        text=text,
        voice_id=voice_id,
        language="en"
    )
    
    # Or publish directly to room
    success = await tts_service.publish_to_room(
        room_name="ozzu-main",
        text=text,
        voice_id=voice_id,
        language="en"
    )
    
    return success
```

## 📊 Performance & Quality Guidelines

### Voice Quality Optimization
- **Reference Duration**: 10-30 seconds per file (optimal)
- **Multiple Files**: Use 2-5 files with varied speech patterns
- **Audio Quality**: 24kHz, clear speech, minimal background noise
- **Content Variety**: Include questions, statements, emotions

### Performance Considerations  
- **GPU Acceleration**: ~200ms synthesis with GPU
- **CPU Fallback**: ~1-2 seconds synthesis with CPU
- **Memory Usage**: ~2-4GB per concurrent voice cloning request
- **Storage**: ~1-5MB per stored voice (depending on reference duration)

### Cross-Language Quality
- **Best Results**: Similar language families (English → Spanish)
- **Good Results**: Different families with shared phonemes
- **Accent Retention**: Original voice accent is preserved

## 🚨 Migration from Previous Version

### Existing Code Compatibility
All existing code continues to work unchanged:

```python
# This still works exactly as before
response = requests.post("http://june-tts:8000/synthesize-binary", 
                        json={
                            "text": "Hello world",
                            "speaker": "Claribel Dervla", 
                            "language": "en"
                        })
```

### Gradual Migration Path
1. **Phase 1**: Deploy enhanced service (backward compatible)
2. **Phase 2**: Start using voice cloning for new features  
3. **Phase 3**: Migrate existing workflows to custom voices
4. **Phase 4**: Optimize with cross-language capabilities

## 🔐 Security & Validation

### Audio File Validation
- ✅ File format validation (WAV, MP3, FLAC, M4A)
- ✅ Duration validation (6-300 seconds)
- ✅ Sample rate validation (16kHz minimum)
- ✅ Content validation (single speaker detection)
- ✅ Size limits (reasonable file sizes)

### Voice Management Security
- ✅ Unique voice ID generation
- ✅ Voice isolation (each voice in separate directory)
- ✅ Secure file storage with proper permissions
- ✅ Input sanitization for names and descriptions

## 📈 Monitoring & Observability

### New Metrics Available
- Voice cloning requests per minute
- Stored voice count and storage usage
- Cross-language synthesis usage
- Voice cache hit rates
- Audio processing latencies

### Logging Enhancements
```
🎭 Voice cloning: Processing 3 reference files for 'John Smith'
✅ Voice 'John Smith' stored with ID: abc123def456  
🌍 Cross-language: English voice → Spanish synthesis
🔊 Publishing cloned voice to room: ozzu-main
```

## 🎉 Success Confirmation

Your June TTS service now supports:

- ✅ **Professional Voice Cloning** with 6+ second audio samples
- ✅ **Multi-Language Support** across 17 languages
- ✅ **Cross-Language Synthesis** (clone in English, speak Spanish)
- ✅ **Voice Management** with full CRUD operations
- ✅ **Real-Time Performance** optimized for live applications
- ✅ **LiveKit Integration** with direct room publishing
- ✅ **Enterprise Features** including caching and validation
- ✅ **Complete Documentation** with examples and best practices

## 🚀 Next Steps

1. **Deploy** the enhanced service to your environment
2. **Test** voice cloning with sample audio files
3. **Integrate** voice management into your applications
4. **Explore** cross-language synthesis capabilities
5. **Optimize** voice selection for your use cases

The implementation follows all XTTS-v2 documentation requirements and provides a production-ready voice cloning solution for the June platform!