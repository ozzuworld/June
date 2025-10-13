# June Platform 🎯

**Complete Voice AI Platform with WebRTC Support**

June Platform is a comprehensive microservices-based voice processing system that combines speech-to-text, text-to-speech, and real-time WebRTC communication capabilities.

## 🚀 **Quick Start (Fresh VM)**

```bash
# 1. Clone the repository
git clone https://github.com/ozzuworld/June.git
cd June

# 2. Configure your environment
cp config.env.example config.env
nano config.env  # Set your domain, email, API keys

# 3. Run the complete installation
sudo ./install.sh
```

**That's it!** One script installs everything:
- ✅ Kubernetes cluster
- ✅ June Platform services (API, Identity, STT, TTS)
- ✅ LiveKit WebRTC server
- ✅ STUNner TURN server
- ✅ SSL certificates
- ✅ Infrastructure (ingress, cert-manager)

## 🏗️ **Architecture**

### Core Services
- **june-orchestrator**: Main API and orchestration service
- **june-idp**: Keycloak-based identity provider
- **june-stt**: Speech-to-text service (GPU required)
- **june-tts**: Text-to-speech service (GPU required)

### WebRTC Stack
- **LiveKit Server**: Modern WebRTC SFU for real-time communication
- **STUNner**: Kubernetes-native TURN server for NAT traversal

### Infrastructure
- **Kubernetes**: Container orchestration
- **ingress-nginx**: HTTP/HTTPS routing
- **cert-manager**: Automatic SSL certificate management
- **PostgreSQL**: Database for identity management

## 🔧 **Configuration**

### Required Environment Variables

Create `config.env` with:

```bash
# Domain Configuration
DOMAIN=your-domain.com
LETSENCRYPT_EMAIL=admin@your-domain.com

# API Keys
GEMINI_API_KEY=your-gemini-api-key
CLOUDFLARE_TOKEN=your-cloudflare-api-token

# Optional: Customize credentials
POSTGRESQL_PASSWORD=your-db-password
KEYCLOAK_ADMIN_PASSWORD=your-admin-password
TURN_USERNAME=your-turn-username
STUNNER_PASSWORD=your-turn-password
```

### DNS Configuration

Point these DNS records to your server's public IP:

```
your-domain.com      A    YOUR_SERVER_IP
*.your-domain.com    A    YOUR_SERVER_IP
```

## 💻 **Services & Endpoints**

After installation, access your services at:

- **API**: `https://api.your-domain.com`
- **Identity Provider**: `https://idp.your-domain.com`
- **Speech-to-Text**: `https://stt.your-domain.com`
- **Text-to-Speech**: `https://tts.your-domain.com`

### WebRTC Configuration

- **LiveKit Server**: `livekit.media.svc.cluster.local` (internal)
- **TURN Server**: `turn:YOUR_SERVER_IP:3478`
- **TURN Credentials**: `june-user` / `Pokemon123!` (configurable)

## 🔍 **Status Monitoring**

```bash
# Check all services
kubectl get pods -A

# Core June services
kubectl get pods -n june-services

# WebRTC services
kubectl get pods -n media
kubectl get pods -n stunner

# Check STUNner gateway
kubectl get gateway -n stunner

# Test TURN server
./test-stunner.sh
```

## 🔄 **Upgrading from Old Janus Setup**

If you're upgrading from the old Janus implementation:

1. **Read the migration guide**: `MIGRATION.md`
2. **Remove old Janus components**:
   ```bash
   kubectl delete deployment june-janus -n june-services
   kubectl delete service june-janus -n june-services
   ```
3. **Run the updated installer**: `sudo ./install.sh`

## 🤼 **Troubleshooting**

### Common Issues

**Services not starting:**
```bash
kubectl describe pods -n june-services
kubectl logs -n june-services deployment/june-orchestrator
```

**WebRTC not working:**
```bash
kubectl logs -n media deployment/livekit
kubectl describe gateway stunner-gateway -n stunner
```

**SSL certificates not issued:**
```bash
kubectl describe certificate -n june-services
kubectl logs -n cert-manager deployment/cert-manager
```

### Getting Help

1. Check service logs: `kubectl logs -n <namespace> <pod-name>`
2. Verify configuration: Review your `config.env` file
3. Check DNS: Ensure your domain points to the correct IP
4. Firewall: Open ports 80, 443, and 3478

## 📚 **Documentation**

- **Migration Guide**: `MIGRATION.md` - Upgrading from Janus to LiveKit
- **Configuration Files**: `k8s/` - Kubernetes manifests
- **Helm Charts**: `helm/june-platform/` - Service definitions

## 📜 **Requirements**

### System Requirements
- **OS**: Ubuntu 20.04+ or similar Linux distribution
- **RAM**: 8GB minimum, 16GB recommended
- **CPU**: 4 cores minimum
- **Storage**: 50GB available space
- **GPU**: Optional, required for STT/TTS services

### Network Requirements
- **Public IP**: Required for external access
- **Ports**: 80, 443, 3478 (TURN) must be accessible
- **Domain**: Valid domain name pointing to your server

## 🔒 **Security**

- All services use TLS/SSL certificates (auto-generated via Let's Encrypt)
- Identity management via Keycloak with OAuth2/OIDC
- Network policies isolate services
- Secrets managed via Kubernetes secrets

## 🏁 **Performance**

- **Horizontal scaling**: Most services can run multiple replicas
- **GPU acceleration**: STT/TTS services support NVIDIA GPUs
- **Caching**: Built-in caching for improved response times
- **Load balancing**: Kubernetes-native load balancing

## 🤝 **Contributing**

Contributions are welcome! Please read the contributing guidelines and submit pull requests.

## 📝 **License**

This project is licensed under the MIT License - see the LICENSE file for details.

---

**Built with ❤️ by the June Platform team**