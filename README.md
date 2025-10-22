# June Platform - AI Voice Chat System

June is a comprehensive AI-powered voice chat platform built with microservices architecture, featuring real-time speech-to-text, text-to-speech, and AI conversation capabilities.

## 🚀 Features

- **Real-time Voice Processing**: WebRTC-based voice communication with LiveKit
- **Advanced STT**: GPU-accelerated Whisper speech recognition
- **High-Quality TTS**: F5-TTS voice synthesis with cloning capabilities  
- **AI Conversations**: Gemini-powered intelligent responses
- **Kubernetes Native**: Cloud-native microservices deployment
- **GPU Scaling**: External GPU support via vast.ai integration
- **Secure Networking**: Tailscale VPN for service-to-service communication

## 🏗️ Architecture

June platform consists of these core services:

- **june-orchestrator**: Central coordinator and AI processing
- **june-stt**: Speech-to-text service using Whisper
- **june-tts**: Text-to-speech service with voice cloning
- **june-gpu-multi**: Combined STT+TTS service for external GPU deployment
- **june-idp**: Identity provider (Keycloak)
- **LiveKit**: WebRTC server for real-time communication

## 🚀 Quick Start

### Prerequisites

- Kubernetes cluster
- GPU support (local or vast.ai)
- Domain name with SSL certificates
- Tailscale account (for external GPU deployment)

### 1. Basic Deployment

```bash
# Clone repository
git clone https://github.com/ozzuworld/June.git
cd June

# Configure environment
cp config.env.example config.env
nano config.env  # Add your configuration

# Deploy with Helm
helm install june helm/june-platform
```

### 2. External GPU Deployment with Tailscale

For deploying GPU services on vast.ai with Tailscale networking:

```bash
# Deploy Tailscale operator
kubectl apply -f k8s/tailscale/

# Deploy GPU service on vast.ai
./scripts/deploy-gpu-multi-tailscale.sh
```

See [Tailscale Deployment Guide](docs/TAILSCALE_DEPLOYMENT.md) for detailed instructions.

## 📁 Repository Structure

```
June/
├── June/services/           # Microservices source code
│   ├── june-orchestrator/   # Central coordinator service
│   ├── june-stt/           # Speech-to-text service
│   ├── june-tts/           # Text-to-speech service
│   ├── june-gpu-multi/     # Combined GPU service for external deployment
│   └── june-idp/           # Identity provider
├── k8s/                    # Kubernetes configurations
│   ├── tailscale/          # Tailscale VPN integration
│   ├── livekit/            # LiveKit WebRTC server
│   └── stunner/            # TURN server configuration
├── helm/                   # Helm charts
├── scripts/                # Deployment and utility scripts
├── docs/                   # Documentation
└── deployments/            # Deployment configurations
```

## 🌐 Networking Solutions

### Tailscale VPN (Recommended)

**Perfect for vast.ai deployment** - solves NAT traversal issues:

✅ Bypasses vast.ai NAT limitations  
✅ Encrypted mesh networking  
✅ Automatic service discovery  
✅ Zero firewall configuration  
✅ Layer 4 networking control  

**Setup**: Follow [Tailscale Deployment Guide](docs/TAILSCALE_DEPLOYMENT.md)

### Alternative Options

- **Direct Public Exposure**: LoadBalancer services with public IPs
- **Reverse Tunnels**: Using ngrok, cloudflared, or similar
- **WireGuard VPN**: Self-hosted VPN solution
- **Nebula Mesh**: Self-managed overlay network

## 🔧 Configuration

### Environment Variables

Key configuration in `config.env`:

```bash
# Domain and SSL
DOMAIN=your-domain.com
LETSENCRYPT_EMAIL=admin@your-domain.com

# API Keys
GEMINI_API_KEY=your_gemini_key
CLOUDFLARE_TOKEN=your_cloudflare_token

# GPU Deployment
ENABLE_STT=vast.ai
ENABLE_TTS=vast.ai
VAST_API_KEY=your_vast_api_key
```

### Service Endpoints (with Tailscale)

- **Orchestrator**: `http://june-orchestrator:8080`
- **LiveKit**: `ws://livekit:7880`
- **TTS**: `http://localhost:8000` (external)
- **STT**: `http://localhost:8001` (external)

## 🚀 Deployment Options

### 1. Local Kubernetes with GPU

```bash
helm install june helm/june-platform \
  --set gpu.enabled=true \
  --set orchestrator.replicas=1
```

### 2. Cloud Kubernetes + External GPU

```bash
# Deploy control plane
helm install june helm/june-platform \
  --set stt.enabled=false \
  --set tts.enabled=false

# Deploy GPU services externally
./scripts/deploy-gpu-multi-tailscale.sh
```

### 3. Hybrid Multi-Cloud

- Control plane: GKE/EKS/AKS
- GPU compute: vast.ai instances
- Networking: Tailscale mesh VPN

## 🔍 Monitoring & Debugging

### Health Checks

```bash
# Service health
curl http://june-orchestrator:8080/healthz
curl http://localhost:8000/healthz  # TTS (external)
curl http://localhost:8001/healthz  # STT (external)

# Container logs
kubectl logs -f deployment/june-orchestrator
docker logs -f june-gpu-multi
```

### Troubleshooting

```bash
# Tailscale connectivity
tailscale status
ping june-orchestrator

# Service discovery
nslookup june-orchestrator
telnet livekit 7880

# GPU verification
nvidia-smi
docker exec june-gpu-multi nvidia-smi
```

## 📚 Documentation

- [Tailscale Deployment Guide](docs/TAILSCALE_DEPLOYMENT.md) - External GPU deployment
- [Architecture Overview](Architecture.MD) - System design and components
- [Service Configuration](k8s/tailscale/README.md) - Tailscale integration details
- [Troubleshooting Guide](docs/TAILSCALE_DEPLOYMENT.md#troubleshooting) - Common issues and solutions

## 🛡️ Security

- **End-to-end encryption** via Tailscale VPN
- **OAuth2/OIDC** authentication with Keycloak
- **Service mesh** security with mTLS
- **Secrets management** via Kubernetes secrets
- **Network policies** for service isolation

## 🎯 Performance

- **Low Latency**: ~50-100ms end-to-end voice processing
- **GPU Acceleration**: CUDA-optimized STT and TTS models
- **Horizontal Scaling**: Multiple GPU instances across regions
- **Caching**: Model and audio caching for faster responses

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests and documentation
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support:

1. Check the [Troubleshooting Guide](docs/TAILSCALE_DEPLOYMENT.md#troubleshooting)
2. Review service logs and connectivity
3. Open an issue with detailed error information
4. Join our community discussions

---

**June Platform**: Bringing AI-powered voice conversations to life with cloud-native architecture and seamless GPU scaling! 🎤🤖