# June Platform - AI Voice Chat System

June is a comprehensive AI-powered voice chat platform built with microservices architecture, featuring real-time speech-to-text, text-to-speech, and AI conversation capabilities with automated deployment and integrated VPN networking.

## 🚀 Features

### Core Platform
- **Real-time Voice Processing**: WebRTC-based voice communication with LiveKit
- **Advanced STT**: GPU-accelerated Whisper speech recognition
- **High-Quality TTS**: F5-TTS voice synthesis with voice cloning capabilities  
- **AI Conversations**: Gemini-powered intelligent responses
- **Kubernetes Native**: Cloud-native microservices deployment
- **Auto-SSL**: Automated Let's Encrypt certificate management

### New Integrated Features
- **🌐 Headscale VPN**: Self-hosted Tailscale-compatible control plane
- **☁️ Vast.ai Provider**: Automated remote GPU resource provisioning
- **🤖 Virtual Kubelet**: Seamless hybrid local/remote compute
- **📦 One-Click Deploy**: Fully automated installation from VM to production

## 🏗️ Architecture

### Microservices
- **june-orchestrator**: Central coordinator and AI processing
- **june-stt**: Speech-to-text service using Whisper
- **june-tts**: Text-to-speech service with voice cloning
- **june-api**: RESTful API gateway
- **june-idp**: Identity provider (Keycloak)
- **LiveKit**: WebRTC server for real-time communication
- **STUNner**: WebRTC TURN/STUN server

### Infrastructure
- **Headscale**: Self-hosted VPN control plane (replaces Tailscale dependency)
- **Virtual Kubelet**: Vast.ai provider for remote GPU resources
- **cert-manager**: Automated SSL certificate management
- **NGINX Ingress**: Load balancing and SSL termination

## 🚀 Quick Start

### Prerequisites

- **Server**: Ubuntu 20.04+ with 16GB RAM, public IP
- **Domain**: Registered domain with Cloudflare DNS management
- **API Keys**: Gemini AI, Cloudflare API token
- **Optional**: Vast.ai API key for remote GPU access

### Automated Installation

```bash
# 1. Clone repository
git clone https://github.com/ozzuworld/June.git
cd June

# 2. Configure installation
cp config.env.example config.env
nano config.env  # Add your domain, API keys, etc.

# 3. Run complete installation (15-30 minutes)
sudo ./scripts/install-orchestrator.sh
```

**That's it!** The script automatically:
- ✅ Installs Kubernetes, Docker, GPU drivers
- ✅ Deploys all June Platform services
- ✅ Configures SSL certificates (Let's Encrypt)
- ✅ Sets up Headscale VPN control plane
- ✅ Integrates Vast.ai remote GPU provider
- ✅ Configures WebRTC with STUNner

### Configuration (`config.env`)

```bash
# Required: Domain and certificates
DOMAIN=your-domain.com
LETSENCRYPT_EMAIL=admin@your-domain.com

# Required: API tokens
GEMINI_API_KEY=your_gemini_api_key
CLOUDFLARE_TOKEN=your_cloudflare_api_token

# Required: Secure passwords
POSTGRESQL_PASSWORD=secure_password
KEYCLOAK_ADMIN_PASSWORD=secure_admin_password
STUNNER_PASSWORD=secure_turn_password

# Optional: Vast.ai remote GPU provider
VAST_API_KEY=vast_api_key_your_key_here
VAST_GPU_TYPE=RTX3060
VAST_MAX_PRICE_PER_HOUR=0.50
```

## 📁 Repository Structure

```
June/
├── June/services/           # Microservices source code
│   ├── june-orchestrator/   # Central coordinator service
│   ├── june-stt/           # Speech-to-text service
│   ├── june-tts/           # Text-to-speech service
│   ├── june-api/           # RESTful API gateway
│   └── june-idp/           # Identity provider
├── k8s/                    # Kubernetes configurations
│   ├── headscale/          # Self-hosted VPN control plane
│   ├── vast-gpu/           # Remote GPU provider
│   ├── livekit/            # WebRTC server
│   ├── stunner/            # TURN server
│   └── june-services/      # Core platform services
├── scripts/                # Installation automation
│   ├── install-orchestrator.sh  # Main installation script
│   └── install/            # Modular installation phases
├── helm/                   # Helm charts
├── docs/                   # Documentation
└── deployments/            # Legacy deployment configs
```

## 🌐 Network Architecture

### Headscale VPN (Self-hosted)

**Replaces external Tailscale dependency** with integrated control plane:

✅ **Self-hosted**: No external dependencies  
✅ **Tailscale Compatible**: Uses existing Tailscale clients  
✅ **Automatic Mesh**: Secure device-to-device networking  
✅ **DNS Integration**: `tail.your-domain.com` mesh DNS  
✅ **Zero Configuration**: Automatically deployed and configured  

#### Connect Devices

```bash
# Create user namespace
kubectl exec -n headscale deployment/headscale -- headscale users create team

# Generate auth key
kubectl exec -n headscale deployment/headscale -- headscale preauthkeys create --user team

# Connect device (install Tailscale client first)
tailscale up --login-server https://headscale.your-domain.com --authkey KEY_FROM_ABOVE
```

### Vast.ai Integration

**Automatic GPU resource provisioning** via Virtual Kubelet:

✅ **Cost Optimization**: Selects cheapest GPU matching requirements  
✅ **Geographic Preference**: Prioritizes North America for low latency  
✅ **Reliability Filtering**: Only uses verified, high-uptime hosts  
✅ **Auto-scaling**: Scales GPU resources up/down based on demand  
✅ **Transparent**: Pods schedule to remote GPUs like local resources  

## 🎯 Service Access

After installation, services are available at:

### Core Platform
- **API Gateway**: `https://api.your-domain.com`
- **Identity Provider**: `https://idp.your-domain.com/admin`
- **STT Service**: `https://stt.your-domain.com` _(GPU required)_
- **TTS Service**: `https://tts.your-domain.com` _(GPU required)_

### VPN & Networking
- **Headscale Control**: `https://headscale.your-domain.com`
- **Mesh Network**: `100.64.0.0/10` (`tail.your-domain.com`)
- **WebRTC TURN**: `turn:your-server-ip:3478`

## 🔧 Advanced Configuration

### Skip Installation Phases

```bash
# Skip VPN and remote GPU (core platform only)
sudo ./scripts/install-orchestrator.sh --skip 11-headscale 12-vast-gpu

# Skip GPU components (CPU-only deployment)
sudo ./scripts/install-orchestrator.sh --skip 02.5-gpu 03.5-gpu-operator 12-vast-gpu

# Development mode (minimal resources)
sudo ./scripts/install-orchestrator.sh --skip 08-livekit 11-headscale 12-vast-gpu
```

### Custom Vast.ai Configuration

```bash
# Budget optimization (East Coast preference)
VAST_GPU_TYPE=RTX3060
VAST_MAX_PRICE_PER_HOUR=0.30
VAST_PREFERRED_REGIONS=US-NY,US-FL,US-VA,US

# Performance optimization (West Coast preference)
VAST_GPU_TYPE=RTX4090
VAST_MAX_PRICE_PER_HOUR=0.70
VAST_PREFERRED_REGIONS=US-CA,US-WA,US-OR,US
```

## 🔍 Monitoring & Management

### Health Checks

```bash
# Core services
kubectl get pods -n june-services

# VPN control plane
kubectl get pods -n headscale

# Remote GPU resources
kubectl get nodes -l type=virtual-kubelet

# SSL certificates
kubectl get certificates -n june-services
```

### Service Logs

```bash
# Platform services
kubectl logs -n june-services deployment/june-api -f
kubectl logs -n june-services deployment/june-orchestrator -f

# VPN control plane
kubectl logs -n headscale deployment/headscale -f

# Remote GPU provider
kubectl logs -n kube-system deployment/virtual-kubelet-vast -f
```

### Device Management

```bash
# List VPN-connected devices
kubectl exec -n headscale deployment/headscale -- headscale nodes list

# Monitor GPU instance selection
kubectl logs -n kube-system deployment/virtual-kubelet-vast | grep "VAST-NA"

# Check service endpoints
curl -k https://api.your-domain.com/health
curl -k https://stt.your-domain.com/health
```

## 📚 Documentation

- **[Complete Installation Guide](docs/INSTALLATION.md)** - Detailed setup instructions
- **[Architecture Overview](Architecture.MD)** - System design and components  
- **[Headscale Setup](k8s/headscale/README.md)** - VPN control plane details
- **[Vast.ai Integration](k8s/vast-gpu/SETUP.md)** - Remote GPU configuration
- **[Troubleshooting Guide](docs/INSTALLATION.md#monitoring--troubleshooting)** - Common issues

## 🛡️ Security Features

- **🔐 Auto-SSL**: Let's Encrypt wildcard certificates with auto-renewal
- **🌐 VPN Mesh**: Encrypted inter-service communication via Headscale
- **🔑 OAuth2/OIDC**: Keycloak identity provider with role-based access
- **🛡️ Network Policies**: Service isolation and traffic control
- **📦 Secrets Management**: Encrypted credential storage
- **🔍 Audit Logging**: Comprehensive service and access logs

## 🎯 Performance Metrics

- **🚀 Latency**: ~50-100ms end-to-end voice processing
- **⚡ GPU Scaling**: Automatic provisioning based on demand
- **🌍 Geographic**: North America-optimized Vast.ai selection
- **💰 Cost**: Typically $0.15-0.50/hour for GPU resources
- **📈 Availability**: 99%+ uptime with reliable host selection

## 🆙 Upgrade & Maintenance

```bash
# Update platform services
helm upgrade june helm/june-platform

# Certificate renewal (automatic via cert-manager)
kubectl get certificates -n june-services

# Update GPU provider configuration
kubectl apply -f k8s/vast-gpu/vast-provider-config.yaml

# Backup critical data
cp -r /root/.june-certs/ /backup/location/
kubectl get all -n june-services -o yaml > june-backup.yaml
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes and add tests
4. Update documentation as needed
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and troubleshooting:

1. **📖 Check Documentation**: [Installation Guide](docs/INSTALLATION.md)
2. **🔍 Review Logs**: `kubectl logs -n june-services deployment/june-api`
3. **🐛 Report Issues**: Open a GitHub issue with detailed information
4. **💬 Community**: Join our discussions and contribute

---

**June Platform**: From fresh VM to production-ready AI voice chat platform in under 30 minutes! 🎤🤖✨