# June Platform - Complete Installation Guide

This guide covers the full automated installation of the June Platform, including the new **Headscale VPN control plane** and **Vast.ai remote GPU provider** integrations.

## Overview

The installation process now includes 12+ modular phases:

### Core Platform (Phases 1-10)
1. **Prerequisites** - System packages and dependencies
2. **Docker** - Container runtime installation
3. **GPU Drivers** - NVIDIA drivers and container runtime (optional)
4. **Kubernetes** - K8s cluster setup with kubeadm
5. **Infrastructure** - Core cluster components (CNI, ingress, etc.)
6. **Helm** - Package manager installation
7. **GPU Operator** - NVIDIA GPU Operator with time-slicing (optional)
8. **Certificates** - Let's Encrypt wildcard SSL certificates
9. **STUNner** - WebRTC TURN/STUN server
10. **LiveKit** - Real-time communication server
11. **June Services** - Core API, STT, TTS, and orchestrator services
12. **Final Setup** - Configuration validation and status checks

### New Extensions (Phases 11-12)
11. **Headscale** - Self-hosted VPN control plane (Tailscale-compatible)
12. **Vast.ai Provider** - Remote GPU resources via Virtual Kubelet

## Prerequisites

### System Requirements
- **OS**: Ubuntu 20.04+ or compatible Linux distribution
- **RAM**: 8GB minimum, 16GB+ recommended
- **Disk**: 50GB+ available space
- **Network**: Public IP address with port 443/80/3478 accessible
- **Root Access**: Installation must run as root

### Required Accounts & API Keys
1. **Domain**: Registered domain with DNS management access
2. **Cloudflare**: Account with API token for DNS challenges
3. **Google AI**: Gemini API key for LLM services
4. **Let's Encrypt**: Email address for certificate notifications
5. **Vast.ai** _(Optional)_: API key for remote GPU access

## Quick Start

### 1. Clone Repository
```bash
git clone https://github.com/ozzuworld/June.git
cd June
```

### 2. Configure Installation
```bash
# Copy configuration template
cp config.env.example config.env

# Edit configuration with your details
nano config.env
```

### 3. Run Installation
```bash
# Full installation (all phases)
sudo ./scripts/install-orchestrator.sh

# Or skip specific phases
sudo ./scripts/install-orchestrator.sh --skip 11-headscale 12-vast-gpu
```

## Configuration Details

### Core Configuration (`config.env`)
```bash
# Domain and certificates
DOMAIN=your-domain.com
LETSENCRYPT_EMAIL=admin@your-domain.com

# API tokens
GEMINI_API_KEY=your_gemini_api_key
CLOUDFLARE_TOKEN=your_cloudflare_api_token

# Database & identity
POSTGRESQL_PASSWORD=secure_password
KEYCLOAK_ADMIN_PASSWORD=secure_admin_password

# STUN/TURN
TURN_USERNAME=june-user
STUNNER_PASSWORD=secure_turn_password

# GPU settings (for local GPUs)
GPU_TIMESLICING_REPLICAS=2
```

### Vast.ai Configuration _(Optional)_
```bash
# Get API key from: https://console.vast.ai/
VAST_API_KEY=vast_api_key_your_key_here

# Instance selection preferences (defaults shown)
VAST_GPU_TYPE=RTX3060              # Preferred GPU model
VAST_MAX_PRICE_PER_HOUR=0.50       # Maximum cost per hour
VAST_MIN_GPU_MEMORY=12             # Minimum VRAM in GB
VAST_RELIABILITY_SCORE=0.95        # Minimum host reliability
VAST_MIN_DOWNLOAD_SPEED=100        # Minimum download speed (Mbps)
VAST_MIN_UPLOAD_SPEED=100          # Minimum upload speed (Mbps)
VAST_DATACENTER_LOCATION=US        # Geographic preference
VAST_PREFERRED_REGIONS=US-CA,US-TX,US-NY,US  # Ordered region preference
```

## Installation Modes

### Complete Installation
Installs everything including VPN and remote GPU capabilities:
```bash
sudo ./scripts/install-orchestrator.sh
```

### Core Platform Only
Skips the optional extensions:
```bash
sudo ./scripts/install-orchestrator.sh --skip 11-headscale 12-vast-gpu
```

### Skip Problematic Phases
Useful for troubleshooting or partial installations:
```bash
# Skip GPU-related phases (for CPU-only deployments)
sudo ./scripts/install-orchestrator.sh --skip 02.5-gpu 03.5-gpu-operator 12-vast-gpu

# Skip certificate management (use existing certs)
sudo ./scripts/install-orchestrator.sh --skip 06-certificates

# Development mode (skip resource-intensive components)
sudo ./scripts/install-orchestrator.sh --skip 02.5-gpu 03.5-gpu-operator 08-livekit 11-headscale 12-vast-gpu
```

## Post-Installation Setup

### DNS Configuration
Point your domain records to your server's public IP:
```
your-domain.com        A    YOUR_SERVER_IP
*.your-domain.com      A    YOUR_SERVER_IP
```

### Service Access
After installation, these services will be available:

#### Core Services
- **API**: `https://api.your-domain.com`
- **Identity Provider**: `https://idp.your-domain.com`
- **STT Service**: `https://stt.your-domain.com` _(if GPU available)_
- **TTS Service**: `https://tts.your-domain.com` _(if GPU available)_

#### Headscale VPN _(if installed)_
- **Control Plane**: `https://headscale.your-domain.com`
- **Network Range**: `100.64.0.0/10`
- **Tailscale Domain**: `tail.your-domain.com`

### Headscale Management

#### Create User Namespace
```bash
kubectl exec -n headscale deployment/headscale -- headscale users create june-team
```

#### Generate Device Registration Key
```bash
# Generate 24-hour auth key
kubectl exec -n headscale deployment/headscale -- headscale preauthkeys create --user june-team --expiration 24h
```

#### Connect Device
```bash
# On your client device with Tailscale installed:
tailscale up --login-server https://headscale.your-domain.com --authkey KEY_FROM_ABOVE
```

#### Manage Devices
```bash
# List connected devices
kubectl exec -n headscale deployment/headscale -- headscale nodes list

# View headscale logs
kubectl logs -n headscale deployment/headscale -f
```

### Vast.ai Management

#### Check Virtual Node Status
```bash
# View virtual kubelet status
kubectl get nodes -l type=virtual-kubelet

# Check virtual kubelet logs
kubectl logs -n kube-system deployment/virtual-kubelet-vast -f
```

#### Monitor GPU Instance Selection
```bash
# View instance selection logs
kubectl logs -n kube-system deployment/virtual-kubelet-vast | grep "VAST-NA"

# Check GPU service deployment
kubectl get pods -o wide | grep vast-gpu
```

#### GPU Services Management
```bash
# Deploy GPU services manually (if not auto-deployed)
kubectl apply -f k8s/vast-gpu/gpu-services-deployment.yaml

# Check service endpoints
kubectl get svc | grep "stt\|tts"
```

## Monitoring & Troubleshooting

### Health Checks
```bash
# Core services status
kubectl get pods -n june-services

# STUNner WebRTC gateway
kubectl get gateway -n stunner

# Certificate status
kubectl get certificates -n june-services

# Headscale VPN (if installed)
kubectl get pods -n headscale

# Virtual GPU nodes (if installed)
kubectl get nodes -l type=virtual-kubelet
```

### Common Issues

#### Certificate Problems
```bash
# Check certificate status
kubectl describe certificate -n june-services

# View cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager

# Restore from backup
kubectl apply -f /root/.june-certs/your-domain-wildcard-tls-backup.yaml
```

#### GPU Service Issues
```bash
# Check local GPU availability
nvidia-smi

# View GPU operator status
kubectl get pods -n gpu-operator-resources

# Check Vast.ai virtual node logs
kubectl logs -n kube-system deployment/virtual-kubelet-vast
```

#### Networking Problems
```bash
# Check ingress controller
kubectl get pods -n ingress-nginx

# Verify STUNner configuration
kubectl get udproute -n stunner

# Test internal connectivity
kubectl exec -it deployment/june-api -- curl http://june-orchestrator:8005/health
```

### Log Locations
```bash
# Installation logs
tail -f /var/log/june-install.log

# Service logs
kubectl logs -n june-services deployment/june-api
kubectl logs -n june-services deployment/june-orchestrator
kubectl logs -n june-services deployment/june-stt  # If GPU available
kubectl logs -n june-services deployment/june-tts  # If GPU available

# Infrastructure logs
kubectl logs -n cert-manager deployment/cert-manager
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller
kubectl logs -n stunner deployment/stunner-gateway-operator
```

## Scaling & Production Notes

### Performance Optimization
- **GPU Time-slicing**: Adjust `GPU_TIMESLICING_REPLICAS` based on workload
- **Vast.ai Budget**: Set appropriate `VAST_MAX_PRICE_PER_HOUR` for your needs
- **Regional Preferences**: Configure `VAST_PREFERRED_REGIONS` for optimal latency

### Security Considerations
- **Certificate Backup**: Regularly backup `/root/.june-certs/`
- **Secrets Management**: Rotate API keys and passwords periodically
- **Network Policies**: Consider implementing Kubernetes NetworkPolicies
- **Headscale Security**: Monitor connected devices and revoke unused auth keys

### Backup & Recovery
```bash
# Backup certificates
cp -r /root/.june-certs/ /backup/location/

# Export Kubernetes configurations
kubectl get all -n june-services -o yaml > june-services-backup.yaml
kubectl get all -n headscale -o yaml > headscale-backup.yaml

# Backup Headscale database
kubectl exec -n headscale deployment/headscale -- cp /var/lib/headscale/db.sqlite /tmp/
kubectl cp headscale/PODNAME:/tmp/db.sqlite ./headscale-db-backup.sqlite
```

## Getting Help

For issues or questions:
1. Check the troubleshooting section above
2. Review installation logs: `tail -f /var/log/june-install.log`
3. Check service status: `kubectl get pods -A`
4. Open an issue on the GitHub repository

## Advanced Configuration

For advanced users, individual components can be customized by editing files in:
- `k8s/` - Kubernetes manifests
- `helm/` - Helm chart configurations  
- `scripts/install/` - Installation phase scripts

Refer to component-specific README files in their respective directories for detailed configuration options.