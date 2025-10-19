# June TTS Service - Voice Cloning Enhanced

Advanced Text-to-Speech service with comprehensive voice cloning capabilities, built on Coqui XTTS-v2.

## 🎯 Features

- **58 Built-in Voices**: Pre-trained speakers in 17 languages
- **Voice Cloning**: Clone any voice from 6+ seconds of audio
- **Voice Management**: Upload, store, and reuse custom voices
- **Cross-Language Synthesis**: Clone voice in one language, speak in another
- **Real-time Processing**: ~200ms latency for live applications
- **LiveKit Integration**: Direct audio publishing to rooms
- **Audio Validation**: Automatic quality checks and optimization
- **Speaker Caching**: Performance optimization for frequently used voices

## 🌍 Supported Languages

English, Spanish, French, German, Italian, Portuguese, Polish, Turkish, Russian, Dutch, Czech, Arabic, Chinese (Simplified), Japanese, Hungarian, Korean, Hindi

## 📋 Voice Cloning Requirements

### Audio Specifications
- **Minimum Duration**: 6 seconds (10+ seconds recommended)
- **Audio Formats**: WAV, MP3, FLAC, M4A
- **Sample Rate**: 16-48kHz (automatically resampled to 24kHz)
- **Quality**: Clear speech, minimal background noise
- **Content**: Single speaker only
- **Multiple Files**: Up to 10 reference files supported for better quality

### Quality Guidelines
- Use high-quality recordings without echo or background noise
- Ensure consistent volume levels across reference files
- Include varied speech patterns (different sentences, emotions)
- Avoid music, sound effects, or multiple speakers

## 🚀 API Endpoints

### Health Check
```http
GET /healthz
```
Returns service status and capabilities.

### Built-in Voice Synthesis
```http
POST /synthesize-binary
Content-Type: application/json

{
    "text": "Hello, this is a test message.",
    "language": "en",
    "speaker": "Claribel Dervla",
    "speed": 1.0
}
```
Returns: Audio file (WAV format)

### Voice Cloning - Upload & Store
```http
POST /clone-voice
Content-Type: multipart/form-data

files: [audio_file_1.wav, audio_file_2.wav]
name: "John Doe"
description: "Professional male voice"
language: "en"
```
Returns: Voice ID for future use

**Example Response:**
```json
{
    "voice_id": "abc123def456",
    "name": "John Doe",
    "status": "created",
    "duration": 45.2,
    "file_count": 2,
    "message": "Voice successfully cloned and stored"
}
```

### Voice Cloning - Synthesize with Stored Voice
```http
POST /synthesize-clone
Content-Type: application/json

{
    "text": "This is synthesized with a cloned voice.",
    "language": "en",
    "voice_id": "abc123def456",
    "speed": 1.0
}
```
Returns: Audio file (WAV format) with cloned voice

### Voice Cloning - One-time Synthesis
```http
POST /synthesize-clone
Content-Type: multipart/form-data

text: "One-time voice cloning example."
language: "en"
speed: 1.0
files: [reference_audio.wav]
```
Returns: Audio file without storing the voice

### Cross-Language Voice Cloning
```http
POST /synthesize-clone
Content-Type: application/json

{
    "text": "Bonjour, comment allez-vous?",
    "language": "fr",
    "voice_id": "english_voice_id",
    "speed": 1.0
}
```
Clones an English voice but synthesizes French text.

### LiveKit Room Publishing
```http
POST /publish-to-room
Content-Type: application/json

{
    "room_name": "ozzu-main",
    "text": "Publishing to LiveKit room.",
    "language": "en",
    "voice_id": "abc123def456",
    "speed": 1.0
}
```
Publishes audio directly to LiveKit room (non-blocking).

### Voice Management

#### List All Voices
```http
GET /voices
```
Returns built-in and custom voices with metadata.

#### Get Voice Details
```http
GET /voices/{voice_id}
```
Returns detailed information about a specific voice.

#### Delete Custom Voice
```http
DELETE /voices/{voice_id}
```
Deletes a custom voice and its associated files.

### Language Information
```http
GET /languages
```
Returns list of supported languages with codes.

### Legacy Endpoints (Backward Compatibility)
```http
GET /speakers
```
Returns basic built-in speaker list (use `/voices` instead).

## 🎵 Usage Examples

### Python Client Example

```python
import requests
import json

# TTS Service URL
TTS_URL = "http://june-tts-service:8000"

# 1. Clone a voice
def clone_voice(audio_files, name, description="", language="en"):
    files = [("files", (f"audio_{i}.wav", open(file, "rb"), "audio/wav")) 
             for i, file in enumerate(audio_files)]
    data = {
        "name": name,
        "description": description,
        "language": language
    }
    
    response = requests.post(f"{TTS_URL}/clone-voice", files=files, data=data)
    return response.json()

# 2. Synthesize with cloned voice
def synthesize_cloned(text, voice_id, language="en", speed=1.0):
    payload = {
        "text": text,
        "language": language,
        "voice_id": voice_id,
        "speed": speed
    }
    
    response = requests.post(f"{TTS_URL}/synthesize-clone", json=payload)
    return response.content  # Audio bytes

# 3. Cross-language synthesis
def cross_language_synthesis(english_voice_id, french_text):
    payload = {
        "text": french_text,
        "language": "fr",
        "voice_id": english_voice_id,
        "speed": 1.0
    }
    
    response = requests.post(f"{TTS_URL}/synthesize-clone", json=payload)
    return response.content

# Example usage
if __name__ == "__main__":
    # Clone voice
    result = clone_voice(
        ["reference1.wav", "reference2.wav"], 
        "My Custom Voice", 
        "High-quality male voice"
    )
    voice_id = result["voice_id"]
    
    # Synthesize in original language
    audio_en = synthesize_cloned("Hello, this is my cloned voice!", voice_id, "en")
    
    # Cross-language synthesis
    audio_es = synthesize_cloned("¡Hola, esta es mi voz clonada!", voice_id, "es")
    
    # Save audio files
    with open("cloned_english.wav", "wb") as f:
        f.write(audio_en)
    
    with open("cloned_spanish.wav", "wb") as f:
        f.write(audio_es)
```

### cURL Examples

```bash
# Clone a voice
curl -X POST "http://june-tts:8000/clone-voice" \
  -F "files=@reference1.wav" \
  -F "files=@reference2.wav" \
  -F "name=John Smith" \
  -F "description=Professional narrator" \
  -F "language=en"

# Synthesize with built-in voice
curl -X POST "http://june-tts:8000/synthesize-binary" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello from built-in voice!",
    "language": "en",
    "speaker": "Claribel Dervla"
  }' \
  --output builtin_voice.wav

# Synthesize with cloned voice
curl -X POST "http://june-tts:8000/synthesize-clone" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello from my cloned voice!",
    "language": "en",
    "voice_id": "your_voice_id_here"
  }' \
  --output cloned_voice.wav

# List all voices
curl -X GET "http://june-tts:8000/voices"

# Health check
curl -X GET "http://june-tts:8000/healthz"
```

## 🔧 Configuration

### Environment Variables

```bash
# LiveKit Configuration
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret
LIVEKIT_WS_URL=wss://your-livekit-server.com

# Service Configuration
SERVICE_PORT=8000
SERVICE_HOST=0.0.0.0
LOG_LEVEL=INFO

# Voice Cloning Limits
MAX_VOICE_FILES=10
MAX_VOICE_DURATION=300
MIN_VOICE_DURATION=6.0

# Storage Paths
VOICES_DIR=/app/voices
TTS_CACHE_DIR=/app/cache
```

## 🚀 Deployment

### Docker Build & Run

```bash
# Build image
docker build -t june-tts:voice-cloning .

# Run with GPU support
docker run --gpus all -p 8000:8000 \
  -e LIVEKIT_API_KEY=your_key \
  -e LIVEKIT_API_SECRET=your_secret \
  -v /data/voices:/app/voices \
  june-tts:voice-cloning

# Run CPU-only
docker run -p 8000:8000 \
  -e TTS_DEVICE=cpu \
  -v /data/voices:/app/voices \
  june-tts:voice-cloning
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-tts
spec:
  replicas: 1
  selector:
    matchLabels:
      app: june-tts
  template:
    metadata:
      labels:
        app: june-tts
    spec:
      containers:
      - name: june-tts
        image: june-tts:voice-cloning
        ports:
        - containerPort: 8000
        env:
        - name: LIVEKIT_API_KEY
          valueFrom:
            secretKeyRef:
              name: livekit-secrets
              key: api-key
        - name: LIVEKIT_API_SECRET
          valueFrom:
            secretKeyRef:
              name: livekit-secrets
              key: api-secret
        volumeMounts:
        - name: voices-storage
          mountPath: /app/voices
        resources:
          requests:
            memory: "4Gi"
            cpu: "1000m"
            nvidia.com/gpu: 1
          limits:
            memory: "8Gi"
            cpu: "2000m"
            nvidia.com/gpu: 1
      volumes:
      - name: voices-storage
        persistentVolumeClaim:
          claimName: voices-pvc
```

## 🎛️ Advanced Features

### Multiple Reference Files for Better Quality

```python
# Use multiple reference files for higher quality voice cloning
files = [
    "speaker_sample_1.wav",  # Neutral speech
    "speaker_sample_2.wav",  # Excited speech
    "speaker_sample_3.wav",  # Question intonation
    "speaker_sample_4.wav",  # Slow and clear
]

result = clone_voice(files, "High Quality Voice", "Multiple reference samples")
```

### Cross-Language Voice Transfer

```python
# Clone an English voice, then speak in Spanish
english_voice = clone_voice(["english_ref.wav"], "English Speaker")
voice_id = english_voice["voice_id"]

# Now synthesize Spanish text with English voice characteristics
spanish_audio = synthesize_cloned(
    "Hola, soy un hablante de inglés hablando español",
    voice_id, 
    language="es"
)
```

### Real-time Processing Optimization

```python
# For real-time applications, use shorter reference audio and caching
def optimize_for_realtime(voice_name, reference_audio):
    # Use single, high-quality 10-15 second reference
    result = clone_voice([reference_audio], voice_name)
    
    # Voice is now cached for fast synthesis
    return result["voice_id"]

# Subsequent synthesis calls will be ~200ms
voice_id = optimize_for_realtime("RT Voice", "short_reference.wav")
audio = synthesize_cloned("Real-time synthesis!", voice_id)
```

## 🔍 Troubleshooting

### Common Issues

1. **Audio too short error**: Ensure reference audio is at least 6 seconds
2. **Poor voice quality**: Use higher quality reference audio (24kHz+, clear speech)
3. **Cross-language accent**: This is expected - the cloned voice retains original accent
4. **Memory issues**: Reduce concurrent requests or use CPU-only mode
5. **LiveKit connection failed**: Verify API keys and websocket URL

### Performance Tips

- Use GPU acceleration for faster processing
- Cache frequently used voices
- Use multiple shorter reference files instead of one long file
- Pre-process audio to remove silence and noise
- Monitor memory usage with multiple concurrent voice cloning requests

## 📊 API Response Formats

### Success Responses

```json
{
  "voice_id": "abc123def456",
  "name": "Custom Voice",
  "status": "created",
  "duration": 25.4,
  "file_count": 3,
  "message": "Voice successfully cloned and stored"
}
```

### Error Responses

```json
{
  "detail": "Audio too short: 4.2s. Minimum 6 seconds required, 10+ recommended."
}
```

## 🔒 Security Considerations

- Validate all uploaded audio files
- Implement rate limiting for voice cloning endpoints
- Store voice files securely with proper access controls
- Monitor disk usage for voice storage
- Sanitize voice names and descriptions

This enhanced TTS service provides enterprise-grade voice cloning capabilities while maintaining the simplicity and performance required for real-time applications.