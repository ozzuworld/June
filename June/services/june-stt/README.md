# June STT Service

Real-time Speech-to-Text service with OpenAI API compatibility and LiveKit integration.

## Features

- **OpenAI API compatibility** - Drop-in replacement for `/v1/audio/transcriptions`
- **Real-time transcription** - LiveKit integration for voice chat
- **Silero VAD** - Intelligent speech detection
- **Multiple formats** - JSON, text, verbose JSON responses
- **GPU/CPU support** - Automatic device selection
- **Accent optimization** - Enhanced for Latin accents and technical vocabulary

## Quick Start

### Docker

```bash
docker run -d \
  -p 8001:8001 \
  -e WHISPER_MODEL=large-v3-turbo \
  -e LIVEKIT_ENABLED=true \
  ozzuworld/june-stt
```

### API Usage

```bash
# Transcribe audio file
curl -X POST "http://localhost:8001/v1/audio/transcriptions" \
  -F "file=@audio.wav" \
  -F "model=large-v3-turbo" \
  -F "response_format=json"
```

```python
# Python with OpenAI client
import openai

client = openai.OpenAI(
    api_key="not-needed",
    base_url="http://localhost:8001/v1/"
)

with open("audio.wav", "rb") as audio_file:
    transcript = client.audio.transcriptions.create(
        model="large-v3-turbo",
        file=audio_file
    )
print(transcript.text)
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPER_MODEL` | `large-v3-turbo` | Model size (tiny/base/small/medium/large/large-v3-turbo) |
| `WHISPER_DEVICE` | `auto` | Device (auto/cuda/cpu) |
| `LIVEKIT_ENABLED` | `true` | Enable LiveKit integration |
| `SILERO_VAD_ENABLED` | `true` | Enable intelligent speech detection |
| `FORCE_LANGUAGE` | `true` | Force English language detection |
| `ACCENT_OPTIMIZATION` | `true` | Optimize for Latin accents |
| `ORCHESTRATOR_URL` | - | June orchestrator endpoint |

## Endpoints

- `POST /v1/audio/transcriptions` - OpenAI-compatible transcription
- `GET /healthz` - Health check
- `GET /stats` - Processing statistics
- `GET /` - Service info

## Architecture

```
Audio Input → Silero VAD → Whisper → Transcript Output
     ↓
LiveKit Integration → Real-time Processing → Orchestrator
```

## Models

| Model | Size | Memory | Speed | Quality |
|-------|------|--------|-------|---------|
| tiny | 39MB | 1GB | Fastest | Basic |
| base | 74MB | 1GB | Fast | Good |
| small | 244MB | 2GB | Medium | Better |
| medium | 769MB | 3GB | Slow | High |
| large-v3-turbo | 809MB | 4GB | Good | Excellent |
| large-v3 | 1.5GB | 6GB | Slowest | Best |

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python main.py
```