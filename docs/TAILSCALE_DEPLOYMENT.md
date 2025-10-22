# Tailscale Integration for June Platform

This guide walks you through deploying **june-gpu-multi** service on vast.ai with Tailscale networking to communicate with your Kubernetes cluster.

## Why Tailscale?

✅ **Solves vast.ai NAT issues** - No more port forwarding headaches  
✅ **Encrypted mesh networking** - Secure service-to-service communication  
✅ **Automatic service discovery** - Services available by hostname  
✅ **Zero firewall configuration** - Works through NAT and firewalls  
✅ **Layer 4 control** - Full networking control as you requested  

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│           Kubernetes Cluster               │
│  ┌─────────────────┐  ┌─────────────────┐  │
│  │ june-orchestrator│  │    LiveKit      │  │
│  │ :8080           │  │ :7880           │  │
│  │ + Tailscale     │  │ + Tailscale     │  │
│  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────┘
                    │
              Tailscale Mesh
                    │
┌─────────────────────────────────────────────┐
│              vast.ai GPU Instance          │
│  ┌─────────────────────────────────────────┐ │
│  │          june-gpu-multi              │ │
│  │  ┌─────────────┐  ┌─────────────┐   │ │
│  │  │    STT      │  │    TTS      │   │ │
│  │  │   :8001     │  │   :8000     │   │ │
│  │  └─────────────┘  └─────────────┘   │ │
│  │            + Tailscale               │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

## Step 1: Deploy Tailscale Operator in Kubernetes

### 1.1 Get Tailscale OAuth Credentials

1. Go to [Tailscale Admin Console](https://login.tailscale.com/admin/settings/oauth)
2. Click **"Generate OAuth Client"**
3. Set scopes: **"Devices (Write)"**
4. Note down `Client ID` and `Client Secret`

### 1.2 Create OAuth Secret

```bash
# Copy template and edit
cp k8s/tailscale/tailscale-secret.yaml.example k8s/tailscale/tailscale-secret.yaml
nano k8s/tailscale/tailscale-secret.yaml

# Replace YOUR_TAILSCALE_CLIENT_ID and YOUR_TAILSCALE_CLIENT_SECRET
```

### 1.3 Deploy Tailscale Operator

```bash
# Deploy the operator
kubectl apply -f k8s/tailscale/tailscale-operator.yaml
kubectl apply -f k8s/tailscale/tailscale-secret.yaml

# Check deployment status
kubectl get pods -n tailscale
kubectl logs -n tailscale deployment/operator
```

## Step 2: Expose Kubernetes Services via Tailscale

### 2.1 Expose Orchestrator Service

```bash
kubectl apply -f k8s/tailscale/june-orchestrator-tailscale.yaml
```

### 2.2 Expose LiveKit Service

```bash
kubectl apply -f k8s/tailscale/livekit-tailscale.yaml
```

### 2.3 Verify Services

```bash
# Check services have Tailscale annotations
kubectl get services -n june-services -o wide
kubectl describe service june-orchestrator-tailscale -n june-services

# Check Tailscale operator logs
kubectl logs -n tailscale deployment/operator
```

## Step 3: Deploy june-gpu-multi on vast.ai

### 3.1 Automated Deployment (Recommended)

```bash
# SSH into your vast.ai instance
ssh root@your-vast-instance

# Clone repository
git clone https://github.com/ozzuworld/June.git
cd June

# Run automated deployment script
chmod +x scripts/deploy-gpu-multi-tailscale.sh
./scripts/deploy-gpu-multi-tailscale.sh
```

The script will:
- Install Tailscale
- Connect to your tailnet
- Test connectivity to K8s services
- Deploy the container with proper configuration

### 3.2 Manual Deployment

#### Install Tailscale
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

#### Test Connectivity
```bash
# Test orchestrator
curl http://june-orchestrator:8080/healthz

# Test LiveKit
telnet livekit 7880
```

#### Deploy Container
```bash
# Create environment file
cp .env.tailscale.example .env.tailscale
nano .env.tailscale  # Fill in your credentials

# Run with Docker Compose
docker-compose -f docker-compose.tailscale.yml up -d

# Or run directly with Docker
docker run -d \
  --name june-gpu-multi \
  --gpus all \
  --network host \
  --env-file .env.tailscale \
  -e ORCHESTRATOR_URL=http://june-orchestrator:8080 \
  -e LIVEKIT_WS_URL=ws://livekit:7880 \
  ozzuworld/june/june-gpu-multi:latest
```

## Step 4: Configuration

### 4.1 Required Environment Variables

```bash
# In .env.tailscale file:
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
BEARER_TOKEN=your_bearer_token
```

### 4.2 Get Credentials from Kubernetes

```bash
# Get LiveKit credentials
kubectl get configmap june-webrtc-config -n june-services -o yaml

# Get bearer token (if configured)
kubectl get secret service-auth-secret -n june-services -o yaml
```

## Step 5: Verification

### 5.1 Check Container Status

```bash
# Container logs
docker logs -f june-gpu-multi

# Health checks
curl http://localhost:8000/healthz  # TTS service
curl http://localhost:8001/healthz  # STT service
```

### 5.2 Test Service Communication

```bash
# Test STT → Orchestrator webhook
# This should show in orchestrator logs when STT processes audio
kubectl logs -f deployment/june-orchestrator -n june-services

# Test Orchestrator → TTS API calls
# This should show in GPU container logs when TTS generates speech
docker logs -f june-gpu-multi
```

### 5.3 Check Tailscale Status

```bash
# On vast.ai instance
tailscale status

# On your local machine (if connected)
tailscale status
```

## Troubleshooting

### Common Issues

#### 1. Services Not Reachable
```bash
# Check Tailscale connectivity
ping june-orchestrator
ping livekit

# Check DNS resolution
nslookup june-orchestrator

# Check operator logs
kubectl logs -n tailscale deployment/operator
```

#### 2. Container Won't Start
```bash
# Check GPU access
nvidia-smi

# Check environment variables
docker exec june-gpu-multi env | grep -E "(LIVEKIT|ORCHESTRATOR)"

# Check container logs
docker logs june-gpu-multi
```

#### 3. Authentication Issues
```bash
# Verify credentials
echo $LIVEKIT_API_KEY
echo $BEARER_TOKEN

# Test webhook manually
curl -X POST \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"test","user_id":"test"}' \
  http://june-orchestrator:8080/api/webhooks/transcript
```

### Debug Commands

```bash
# Check all Tailscale services
kubectl get services -A | grep tailscale

# Check network connectivity from container
docker exec -it june-gpu-multi bash
ping june-orchestrator
telnet livekit 7880

# Monitor webhook traffic
kubectl logs -f deployment/june-orchestrator -n june-services | grep webhook
```

## Advanced Configuration

### Custom Hostnames

To use custom hostnames, modify the service annotations:

```yaml
annotations:
  tailscale.com/hostname: "my-custom-orchestrator"
```

### ACL Policies

For additional security, configure ACL policies in [Tailscale Admin Console](https://login.tailscale.com/admin/acls):

```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["tag:k8s", "tag:june-gpu"],
      "dst": ["tag:k8s:*", "tag:june-gpu:*"]
    }
  ],
  "tagOwners": {
    "tag:k8s": ["your-email@domain.com"],
    "tag:june-gpu": ["your-email@domain.com"]
  }
}
```

## Performance Notes

- **Latency**: Tailscale adds ~5-10ms overhead
- **Bandwidth**: No significant impact for voice data
- **CPU**: Minimal CPU usage for encryption
- **Memory**: ~10-20MB per Tailscale client

## Next Steps

Once everything is working:

1. **Scale**: Deploy multiple GPU instances across different vast.ai regions
2. **Monitor**: Set up monitoring for service health and performance
3. **Automate**: Create CI/CD pipelines for automatic deployment
4. **Optimize**: Fine-tune model parameters and caching strategies

## Support

For issues:
1. Check the troubleshooting section above
2. Review Tailscale operator logs: `kubectl logs -n tailscale deployment/operator`
3. Check service connectivity: `ping service-name`
4. Verify credentials and environment variables

Tailscale provides **reliable networking that bypasses vast.ai NAT limitations** while giving you full Layer 4 control as requested! 🎉