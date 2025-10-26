# June Platform: vast.ai GPU Deployment Guide

This guide covers deploying June STT and TTS services on a single GPU instance at vast.ai, optimized for cost-effectiveness and performance.

## Overview

The deployment strategy uses **multi-container GPU sharing** to run both services efficiently:
- **june-stt**: Speech-to-Text using Whisper models
- **june-tts**: Text-to-Speech using F5-TTS/Coqui models
- **Single GPU**: Both services share GPU resources via CUDA
- **Tailscale**: Secure networking integration

## Prerequisites

### 1. vast.ai Account Setup
- Create account at [vast.ai](https://vast.ai)
- Add payment method and credits
- Generate SSH key for instance access

### 2. Tailscale Configuration
- Set up Tailscale account
- Generate auth key for automatic connection
- Configure your tailnet for June services

### 3. Docker Registry (Optional)
- Push your custom images to registry
- Or use the deployment script to build locally

## Quick Start

### 1. Instance Selection

Recommended GPU instances (in priority order):
- **RTX 3090** (24GB VRAM) - Best value for memory
- **RTX 4080** (16GB VRAM) - Good performance/cost ratio
- **RTX 4070** (12GB VRAM) - Budget option

Minimum specs:
- **RAM**: 16GB+
- **Disk**: 50GB+ SSD
- **vCPUs**: 8+
- **Location**: USA/Canada (for low latency)

### 2. Initial Setup

```bash
# Connect to your vast.ai instance
ssh root@<instance-ip>

# Clone your repository
git clone https://github.com/ozzuworld/June.git
cd June

# Set environment variables
export TAILSCALE_AUTH_KEY="your-tailscale-key"
export DOCKER_REGISTRY_USER="your-username"
export DOCKER_REGISTRY_TOKEN="your-token"

# Make script executable
chmod +x scripts/deploy-vastai.sh

# Run deployment
./scripts/deploy-vastai.sh
```

### 3. Manual Deployment Alternative

```bash
# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.21.0/docker-compose-linux-x86_64" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Setup Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --authkey="$TAILSCALE_AUTH_KEY"

# Create workspace
mkdir -p /workspace/{models,cache,logs}
sudo chown -R 1001:1001 /workspace/{models,cache}

# Deploy services
docker-compose -f docker-compose.vastai.yml up -d
```

## Configuration

### Environment Variables

Key configuration options in `docker-compose.vastai.yml`:

```yaml
# GPU Memory Allocation
CUDA_MEMORY_FRACTION=0.4  # STT: 40% GPU memory
CUDA_MEMORY_FRACTION=0.5  # TTS: 50% GPU memory

# Service Endpoints
PORT=8001  # STT service
PORT=8000  # TTS service

# Model Caching
WHISPER_CACHE_DIR=/app/models
TTS_CACHE_PATH=/app/cache

# Orchestrator Integration
ORCHESTRATOR_URL=http://localhost:8080
LIVEKIT_WS_URL=ws://june-orchestrator:7880
```

### GPU Resource Management

Memory allocation strategy:
- **STT (Whisper)**: ~3-4GB for large models
- **TTS (F5-TTS)**: ~4-6GB for voice cloning
- **CUDA Overhead**: ~1-2GB
- **Buffer**: ~2-3GB for peaks
- **Total**: ~10-15GB (safe for 16GB+ GPUs)

## Monitoring and Management

### Health Checks

```bash
# Check service status
curl http://localhost:8001/healthz  # STT
curl http://localhost:8000/healthz  # TTS

# View logs
docker logs june-stt-vastai -f
docker logs june-tts-vastai -f

# GPU monitoring
nvidia-smi
gpustat  # If installed
```

### Using the Monitor Command

After deployment, use the built-in monitoring:

```bash
# Quick status check
monitor

# Detailed logs
docker-compose -f docker-compose.vastai.yml logs -f

# Resource usage
htop
iftop
```

### Service Management

```bash
# Restart services
docker-compose -f docker-compose.vastai.yml restart

# Stop services
docker-compose -f docker-compose.vastai.yml down

# Update and redeploy
git pull
docker-compose -f docker-compose.vastai.yml up -d --build

# Scale individual services
docker-compose -f docker-compose.vastai.yml up -d --scale june-stt=1
```

## Integration with June Platform

### Orchestrator Configuration

Update your orchestrator service to connect to vast.ai instance:

```yaml
# In orchestrator config
STT_SERVICE_URL: "http://<tailscale-ip>:8001"
TTS_SERVICE_URL: "http://<tailscale-ip>:8000"
```

### Tailscale Networking

Services are accessible via Tailscale:
- **STT**: `http://<instance-tailscale-ip>:8001`
- **TTS**: `http://<instance-tailscale-ip>:8000`
- **WebRTC**: Direct P2P through Tailscale mesh

### Load Balancing

For production, consider multiple instances:

```bash
# Deploy on multiple instances
for region in us-east us-west; do
  vast.ai create instance --gpu "RTX 3090" --region $region
done

# Update orchestrator with multiple endpoints
STT_ENDPOINTS: [
  "http://instance1-tailscale-ip:8001",
  "http://instance2-tailscale-ip:8001"
]
```

## Troubleshooting

### Common Issues

#### GPU Memory Errors
```bash
# Check GPU usage
nvidia-smi

# Reduce memory allocation
# Edit docker-compose.vastai.yml:
CUDA_MEMORY_FRACTION=0.3  # Reduce from 0.4
```

#### Service Health Failures
```bash
# Check service logs
docker logs june-stt-vastai --tail 50
docker logs june-tts-vastai --tail 50

# Verify model downloads
ls -la /workspace/models/

# Test endpoints manually
curl -v http://localhost:8001/healthz
```

#### Tailscale Connection Issues
```bash
# Check Tailscale status
tailscale status

# Reconnect if needed
sudo tailscale up --authkey="$TAILSCALE_AUTH_KEY" --force-reauth

# Test connectivity
ping june-orchestrator  # Should resolve via MagicDNS
```

#### Docker Compose Errors
```bash
# Validate compose file
docker-compose -f docker-compose.vastai.yml config

# Check Docker daemon
sudo systemctl status docker

# Restart Docker if needed
sudo systemctl restart docker
```

### Performance Optimization

#### Model Caching
```bash
# Pre-download models to reduce startup time
docker run --rm -v /workspace/models:/models \
  nvidia/cuda:11.8-runtime-ubuntu22.04 \
  bash -c "cd /models && wget <model-urls>"
```

#### Memory Tuning
```bash
# Monitor memory usage patterns
watch -n 1 'nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader'

# Adjust allocations based on actual usage
# STT typically needs less, TTS needs more
```

## Cost Optimization

### Instance Management
```bash
# Stop instance when not in use
vast.ai stop instance <instance-id>

# Use spot instances for development
vast.ai create instance --interruptible

# Monitor costs
vast.ai show instances --costs
```

### Auto-scaling (Advanced)
```bash
# Create auto-stop script
echo '*/30 * * * * if [ $(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits) -lt 10 ]; then echo "Low usage"; fi' | crontab -
```

## Security Considerations

- **Tailscale**: All traffic encrypted via WireGuard
- **Firewall**: Only SSH and Tailscale ports exposed
- **Container Security**: Services run as non-root users
- **Model Security**: Models cached in private volumes

## Backup and Recovery

```bash
# Backup model cache
tar -czf models-backup-$(date +%Y%m%d).tar.gz /workspace/models/

# Backup configuration
cp docker-compose.vastai.yml /workspace/backups/

# Restore on new instance
tar -xzf models-backup-*.tar.gz -C /
```

## Support

For issues:
1. Check service logs: `docker logs <container-name>`
2. Verify GPU status: `nvidia-smi`
3. Test network connectivity: `tailscale ping <peer>`
4. Review this documentation
5. Open GitHub issue with logs and configuration