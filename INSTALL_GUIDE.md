# June Platform Installation Guide

This guide provides step-by-step instructions for deploying the June voice processing platform.

## Prerequisites

- Ubuntu 20.04+ server with root access
- At least 16GB RAM (32GB recommended for GPU workloads)
- 100GB+ storage space
- Domain name with Cloudflare DNS management
- Cloudflare API token with DNS:Edit permissions
- Gemini API key from Google AI Studio

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/ozzuworld/June.git
cd June
```

### 2. Make Scripts Executable

```bash
chmod +x scripts/generate-manifests.sh
chmod +x scripts/install-k8s/*.sh
```

### 3. Run Installation

```bash
# Full installation (recommended)
sudo ./scripts/install-k8s/install-june-platform.sh

# Or install components separately
sudo ./scripts/install-k8s/install-june-platform.sh --skip-gpu --skip-github
```

## Installation Steps Explained

The main installation script (`install-june-platform.sh`) performs these steps:

### Step 1: Prerequisites Check
- Verifies Ubuntu OS
- Installs basic tools (curl, wget, git, jq, etc.)

### Step 2: Core Infrastructure
- Installs Docker and Kubernetes
- Sets up ingress-nginx with hostNetwork mode
- Installs cert-manager for SSL certificates
- Configures domain and certificate management

### Step 3: Networking
- Installs MetalLB for LoadBalancer services
- Sets up STUNner for WebRTC TURN/STUN services
- Configures Gateway API v1

### Step 4: GPU Operator (Optional)
- Installs NVIDIA GPU Operator with time-slicing
- Configures GPU sharing for multiple containers

### Step 5: GitHub Actions Runner (Optional)
- Sets up self-hosted GitHub Actions runner
- Enables CI/CD automation

### Step 6: Application Secrets
- Creates Kubernetes secrets for API keys
- Configures service authentication tokens

### Step 7: Manifest Processing & Deployment
- Processes template manifests with actual configuration
- Deploys all June services to Kubernetes

## Configuration Options

During installation, you'll be prompted for:

- **Primary Domain**: Your main domain (e.g., `example.com`)
- **Subdomains**: API, IDP, STT, TTS endpoints
- **Let's Encrypt Email**: For SSL certificate generation
- **Cloudflare API Token**: For DNS challenge validation
- **Gemini API Key**: For AI processing capabilities
- **TURN Credentials**: For WebRTC connectivity

## Advanced Usage

### Selective Installation

```bash
# Skip GPU and GitHub runner
sudo ./scripts/install-k8s/install-june-platform.sh --skip-gpu --skip-github

# Skip networking (if already configured)
sudo ./scripts/install-k8s/install-june-platform.sh --skip-networking

# Install infrastructure only
sudo ./scripts/install-k8s/install-june-platform.sh --skip-deploy
```

### Certificate Management

```bash
# Backup existing certificates
sudo ./scripts/install-k8s/backup-restore-cert.sh backup

# List available backups
sudo ./scripts/install-k8s/backup-restore-cert.sh list

# Restore from backup
sudo ./scripts/install-k8s/backup-restore-cert.sh restore
```

### Manual Manifest Processing

```bash
# Process templates with current configuration
sudo ./scripts/generate-manifests.sh

# Deploy processed manifests
kubectl apply -f k8s/complete-manifests-processed.yaml
```

## Post-Installation

### 1. DNS Configuration

Point your domain and wildcard subdomain to your server's IP:

```
example.com        A    YOUR_SERVER_IP
*.example.com      A    YOUR_SERVER_IP
```

### 2. Verify Deployment

```bash
# Check all services
kubectl get all -n june-services

# Monitor pod startup
kubectl get pods -n june-services -w

# Check ingress and certificates
kubectl get ingress -n june-services
kubectl get certificates -n june-services
```

### 3. Test Services

```bash
# Test STUNner connectivity
python3 scripts/test-turn-server.py

# Check service endpoints
curl https://api.example.com/healthz
curl https://stt.example.com/healthz
curl https://tts.example.com/healthz
```

## Troubleshooting

### Common Issues

1. **Certificate Issues**
   ```bash
   kubectl describe certificate -n june-services
   kubectl logs -n cert-manager -l app.kubernetes.io/name=cert-manager
   ```

2. **Pod Startup Issues**
   ```bash
   kubectl describe pod -n june-services <pod-name>
   kubectl logs -n june-services <pod-name>
   ```

3. **STUNner Gateway Issues**
   ```bash
   kubectl get gateway -n stunner
   kubectl logs -n stunner-system -l app.kubernetes.io/name=stunner-gateway-operator
   ```

### Configuration Files

All configuration is stored in `/root/.june-config/`:

- `infrastructure.env` - Basic infrastructure settings
- `domain-config.env` - Domain and certificate configuration
- `networking.env` - STUNner and networking settings
- `secrets.env` - API keys and sensitive data
- `ice-servers.json` - WebRTC ICE server configuration

## Scaling and Production

### High Availability

- Use external databases (PostgreSQL)
- Configure ingress with multiple replicas
- Set up proper monitoring and alerting

### Security

- Regularly update certificates
- Rotate API keys and secrets
- Implement network policies
- Use private container registries

### Performance

- Configure GPU sharing properly
- Monitor resource usage
- Scale deployments based on load
- Optimize container resource limits

## Support

For issues and questions:

- Check the [GitHub Issues](https://github.com/ozzuworld/June/issues)
- Review logs using the commands above
- Verify DNS and certificate configuration
- Ensure all prerequisites are met

## License

This project is licensed under the terms specified in the repository.