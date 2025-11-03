# June AI Voice Assistant Platform

![June Platform](https://img.shields.io/badge/June-AI%20Voice%20Platform-blue?style=for-the-badge)
![Version](https://img.shields.io/badge/Version-2.0.0-green?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)

June is a comprehensive AI-powered voice assistant platform built for real-time conversational experiences. The platform combines state-of-the-art **Chatterbox TTS** speech synthesis, real-time audio streaming, and intelligent conversation management.

## 🚀 Features

### Core Capabilities
- **Real-time Voice Conversations**: Ultra-low latency voice interactions using WebRTC
- **Chatterbox TTS Engine**: State-of-the-art open-source TTS with streaming audio generation
- **Voice Cloning**: Zero-shot voice cloning with reference audio samples
- **LiveKit Integration**: Professional-grade WebRTC infrastructure
- **GPU Optimization**: CUDA-accelerated speech synthesis
- **Streaming AI**: Real-time response generation with phrase-level TTS

### Platform Architecture 
- **Microservices Design**: Scalable, containerized service architecture
- **Kubernetes Native**: Built for cloud-native deployment
- **Smart TTS Queue**: GPU-aware processing and natural conversation flow
- **Session Management**: Persistent conversation context and memory
- **Authentication**: Secure service-to-service and user authentication

### AI & Conversation
- **ChatGPT-style Conversational AI**: Context-aware dialogue management
- **Intent Recognition**: Smart conversation flow and topic tracking
- **Emotion Control**: Adjustable speech expressiveness and emotion levels
- **Multi-language Support**: Cross-language voice synthesis capabilities
- **Skill System**: Extensible AI capabilities and persona management

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│           LiveKit Room: "ozzu-main"                 │
│                                                     │
│  Participant 1: Client (user)                      │
│      - Publishes: microphone audio                 │
│      - Subscribes: TTS audio responses             │
│                                                     │
│  Participant 2: STT Service                        │
│      - Subscribes: ALL audio tracks                │
│      - Processing: Transcribe → Webhook            │
│                                                     │
│  Participant 3: Chatterbox TTS Service             │
│      - Publishes: AI response audio                │
│      - Triggered by: Orchestrator via API          │
│      - Features: Voice cloning, streaming           │
│                                                     │
└─────────────────────────────────────────────────────┘
                        ↓
                  Orchestrator
              (webhook receiver + AI)
```

## 📋 Services

### june-orchestrator
Central coordination service managing:
- Webhook processing from STT service
- AI conversation processing
- TTS coordination and streaming
- Session and context management
- Authentication and security

### june-tts (NEW - v2.0)
High-performance TTS service featuring:
- **Chatterbox TTS engine** with GPU acceleration
- **Streaming audio generation** with customizable chunk sizes
- **Voice cloning** with reference audio samples
- **LiveKit WebRTC publishing** for real-time audio
- **Emotion control** with Chatterbox's exaggeration parameter
- **Advanced voice control** with temperature and cfg_weight parameters
- **Comprehensive metrics and monitoring**

### june-stt
Speech-to-text service with:
- Real-time audio transcription
- Faster-whisper integration
- LiveKit room participation
- Webhook notifications to orchestrator

### june-idp
Identity provider service handling:
- User authentication
- Service-to-service auth
- Token management
- Permission control

## 🛠️ Quick Start

### Prerequisites
- Docker and Docker Compose
- Kubernetes cluster (for production)
- NVIDIA GPU (recommended for Chatterbox TTS)
- LiveKit server instance

### Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/ozzuworld/June.git
   cd June
   ```

2. **Configure environment**
   ```bash
   cp config.env.example config.env
   # Edit config.env with your settings
   ```

3. **Start services**
   ```bash
   # Start with Docker Compose
   docker-compose up -d
   
   # Or use the helper script
   ./scripts/start-dev.sh
   ```

4. **Deploy to Kubernetes**
   ```bash
   # Apply Kubernetes manifests
   kubectl apply -f k8s/
   
   # Or use Helm charts
   helm install june ./helm/june-platform
   ```

### Chatterbox TTS Service Configuration

The june-tts service supports extensive configuration via environment variables:

```bash
# Chatterbox TTS Engine Settings
TTS_ENGINE=chatterbox           # Only Chatterbox TTS supported
TTS_DEVICE=cuda                 # Device (cuda/cpu/auto)
CHATTERBOX_CHUNK_SIZE=25        # Tokens per streaming chunk
CHATTERBOX_EXAGGERATION=0.5     # Emotion intensity (0.0-1.5)
CHATTERBOX_TEMPERATURE=0.9      # Voice randomness (0.1-1.0)
CHATTERBOX_CFG_WEIGHT=0.3       # Guidance weight (0.0-1.0)

# LiveKit Integration
LIVEKIT_WS_URL=wss://livekit.ozzu.world
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-secret

# Performance Tuning
TTS_SAMPLE_RATE=24000           # Audio sample rate
TTS_MAX_CONCURRENT=4            # Max concurrent requests
CUDA_VISIBLE_DEVICES=0          # GPU device selection
```

## 🎯 API Endpoints

### Chatterbox TTS Service (june-tts)
```bash
# Synthesize and stream to LiveKit room with voice cloning
POST /api/tts/synthesize
{
  "text": "Hello, this is June speaking with Chatterbox TTS!",
  "room_name": "ozzu-main",
  "voice_reference": "/path/to/reference_voice.wav",
  "speed": 1.0,
  "emotion_level": 0.6,
  "temperature": 0.9,
  "cfg_weight": 0.3
}

# Get Chatterbox capabilities
GET /api/voices
{
  "engine": "chatterbox",
  "voice_cloning": true,
  "streaming": true,
  "parameters": {
    "emotion_level": {"min": 0.0, "max": 1.5, "default": 0.5},
    "temperature": {"min": 0.1, "max": 1.0, "default": 0.9},
    "cfg_weight": {"min": 0.0, "max": 1.0, "default": 0.3}
  }
}

# Health check
GET /health

# Service metrics
GET /metrics
```

### Orchestrator Service
```bash
# Webhook endpoint for STT
POST /api/webhook/stt

# LiveKit token generation
POST /api/livekit/token

# Conversation management
GET /api/conversation/{session_id}
POST /api/conversation/process

# Voice management
GET /api/voices
```

## 🔧 Configuration

### Chatterbox TTS Parameters
The platform supports advanced Chatterbox TTS configuration:

```json
{
  "chatterbox_parameters": {
    "exaggeration": {
      "description": "Emotion intensity and expressiveness",
      "range": "0.0-1.5",
      "default": 0.5
    },
    "temperature": {
      "description": "Voice randomness and variation",
      "range": "0.1-1.0", 
      "default": 0.9
    },
    "cfg_weight": {
      "description": "Guidance weight for voice control",
      "range": "0.0-1.0",
      "default": 0.3
    },
    "chunk_size": {
      "description": "Tokens per streaming chunk",
      "range": "1-100",
      "default": 25
    }
  }
}
```

### Performance Optimization
- **GPU Memory Management**: Configurable memory fraction and model caching
- **Streaming Chunks**: Configurable token-based chunking for optimal latency
- **Voice Cloning**: Per-request voice cloning with reference audio
- **Connection pooling**: Efficient LiveKit connection reuse

## 📊 Monitoring & Metrics

The platform provides comprehensive monitoring:

### Chatterbox TTS Metrics
- First chunk latency (target: <500ms)
- Voice cloning request counts
- GPU utilization and memory usage
- Streaming completion rates
- Emotion and temperature parameter usage

### Conversation Metrics
- Session duration and message counts
- AI response times
- User engagement patterns
- Error rates and recovery

## 🔒 Security

- **Service Authentication**: JWT-based service-to-service auth
- **Rate Limiting**: Configurable per-user and per-service limits
- **Cost Protection**: Daily spend limits and circuit breakers
- **CORS Configuration**: Flexible origin management
- **TLS Encryption**: End-to-end encrypted communications

## 🚀 Deployment

### Kubernetes Production Setup

1. **Configure secrets**
   ```bash
   kubectl create secret generic june-secrets \
     --from-literal=livekit-api-key=your-key \
     --from-literal=livekit-api-secret=your-secret
   ```

2. **Deploy services**
   ```bash
   kubectl apply -f k8s/june-namespace.yaml
   kubectl apply -f k8s/june-services.yaml
   kubectl apply -f k8s/june-deployments.yaml
   ```

3. **Configure ingress**
   ```bash
   kubectl apply -f k8s/june-ingress.yaml
   ```

### GPU Node Requirements for Chatterbox TTS
For optimal performance:
- NVIDIA GPU with CUDA 11.8+ support
- Minimum 8GB GPU memory for Chatterbox models
- NVIDIA Container Toolkit installed
- Kubernetes GPU device plugin

## 🧪 Testing

### Unit Tests
```bash
# Run service tests
pytest June/services/june-tts/tests/
pytest June/services/june-orchestrator/tests/
```

### Integration Tests
```bash
# Test Chatterbox TTS service
curl -X POST http://localhost:8000/api/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{
    "text":"Hello from Chatterbox TTS!", 
    "room_name":"test-room",
    "emotion_level": 0.7,
    "temperature": 0.8
  }'

# Test orchestrator
curl -X GET http://localhost:8080/health
```

### Load Testing
```bash
# Chatterbox TTS load test
k6 run scripts/load-test-chatterbox.js

# End-to-end conversation test
k6 run scripts/load-test-conversation.js
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Workflow
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

### Code Standards
- Python: Black formatting, type hints, docstrings
- Docker: Multi-stage builds, security scanning
- Kubernetes: Resource limits, health checks
- Documentation: Keep README and docs updated

## 📈 Roadmap

### Q4 2025
- [ ] Enhanced Chatterbox voice cloning with fewer reference samples
- [ ] Multi-language conversation support
- [ ] Advanced emotion recognition and synthesis
- [ ] Real-time voice conversion with Chatterbox

### Q1 2026
- [ ] Mobile SDK for iOS/Android integration
- [ ] Advanced conversation analytics
- [ ] Custom Chatterbox model training pipeline
- [ ] Edge deployment optimizations

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Documentation**: [docs.june-ai.com](https://docs.june-ai.com)
- **Issues**: [GitHub Issues](https://github.com/ozzuworld/June/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ozzuworld/June/discussions)
- **Email**: support@june-ai.com

## 🙏 Acknowledgments

- **Chatterbox TTS**: High-quality open-source TTS engine by Resemble AI
- **LiveKit**: Professional WebRTC infrastructure
- **FastAPI**: Modern Python web framework
- **Kubernetes**: Container orchestration platform

---

**June AI Platform v2.0** - Powered by Chatterbox TTS for human-like voice conversations.
