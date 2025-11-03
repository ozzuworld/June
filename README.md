# June AI Voice Assistant Platform

![June Platform](https://img.shields.io/badge/June-AI%20Voice%20Platform-blue?style=for-the-badge)
![Version](https://img.shields.io/badge/Version-2.0.0-green?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)

June is a comprehensive AI-powered voice assistant platform built for real-time conversational experiences. The platform combines state-of-the-art speech synthesis, real-time audio streaming, and intelligent conversation management.

## 🚀 Features

### Core Capabilities
- **Real-time Voice Conversations**: Ultra-low latency voice interactions using WebRTC
- **Advanced TTS Engine**: Chatterbox/Kokoro TTS with streaming audio generation
- **LiveKit Integration**: Professional-grade WebRTC infrastructure
- **GPU Optimization**: CUDA-accelerated speech synthesis
- **Streaming AI**: Real-time response generation with phrase-level TTS
- **Voice Cloning**: Zero-shot voice cloning with 7-20 seconds of reference audio

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
│  Participant 3: TTS Service                        │
│      - Publishes: AI response audio                │
│      - Triggered by: Orchestrator via API          │
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
- **Chatterbox/Kokoro TTS engine** with GPU acceleration
- **Streaming audio generation** with 200ms chunks
- **LiveKit WebRTC publishing** for real-time audio
- **Voice selection and emotion control**
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
- NVIDIA GPU (recommended for TTS)
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

### TTS Service Configuration

The new june-tts service supports extensive configuration via environment variables:

```bash
# TTS Engine Settings
TTS_ENGINE=kokoro              # TTS engine (kokoro/chatterbox)
TTS_DEVICE=cuda               # Device (cuda/cpu/auto)
TTS_DEFAULT_VOICE=af_bella    # Default voice ID
TTS_MAX_CONCURRENT=4          # Max concurrent requests

# LiveKit Integration
LIVEKIT_WS_URL=wss://livekit.ozzu.world
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-secret

# Performance Tuning
TTS_SAMPLE_RATE=24000         # Audio sample rate
CUDA_VISIBLE_DEVICES=0        # GPU device selection
```

## 🎯 API Endpoints

### TTS Service (june-tts)
```bash
# Synthesize and stream to LiveKit room
POST /api/tts/synthesize
{
  "text": "Hello, this is June speaking!",
  "room_name": "ozzu-main",
  "voice_id": "af_bella",
  "speed": 1.0,
  "emotion_level": 0.6
}

# List available voices
GET /api/voices

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
POST /api/voices/profile
```

## 🔧 Configuration

### Voice Configuration
The platform supports multiple high-quality voices:

```json
{
  "af_bella": {
    "name": "Bella",
    "language": "en",
    "gender": "female",
    "accent": "american",
    "description": "Warm, friendly female voice"
  },
  "am_adam": {
    "name": "Adam", 
    "language": "en",
    "gender": "male",
    "accent": "american",
    "description": "Deep, authoritative male voice"
  }
}
```

### Performance Optimization
- **GPU Memory Management**: Configurable memory fraction and caching
- **Streaming Chunks**: 200ms chunks for optimal latency/quality balance
- **Concurrent Processing**: Smart queuing prevents GPU overload
- **Connection pooling**: Efficient LiveKit connection reuse

## 📊 Monitoring & Metrics

The platform provides comprehensive monitoring:

### TTS Metrics
- First chunk latency (target: <500ms)
- GPU utilization and memory usage
- Audio quality scores
- Concurrent request handling
- Stream completion rates

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

### GPU Node Requirements
For optimal TTS performance:
- NVIDIA GPU with CUDA 11.8+ support
- Minimum 8GB GPU memory
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
# Test TTS service
curl -X POST http://localhost:8000/api/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello world", "room_name":"test-room"}'

# Test orchestrator
curl -X GET http://localhost:8080/health
```

### Load Testing
```bash
# TTS load test
k6 run scripts/load-test-tts.js

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
- [ ] Enhanced voice cloning with fewer reference samples
- [ ] Multi-language conversation support
- [ ] Advanced emotion recognition and synthesis
- [ ] Real-time voice conversion

### Q1 2026
- [ ] Mobile SDK for iOS/Android integration
- [ ] Advanced conversation analytics
- [ ] Custom voice training pipeline
- [ ] Edge deployment optimizations

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Documentation**: [docs.june-ai.com](https://docs.june-ai.com)
- **Issues**: [GitHub Issues](https://github.com/ozzuworld/June/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ozzuworld/June/discussions)
- **Email**: support@june-ai.com

## 🙏 Acknowledgments

- **Chatterbox TTS**: High-quality open-source TTS engine
- **LiveKit**: Professional WebRTC infrastructure
- **FastAPI**: Modern Python web framework
- **Kubernetes**: Container orchestration platform

---

**June AI Platform v2.0** - Bringing human-like voice conversations to applications worldwide.
