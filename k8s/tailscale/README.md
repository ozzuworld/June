# Tailscale Integration for June Platform

This directory contains Tailscale networking configuration for enabling secure communication between your Kubernetes cluster and external GPU services running on vast.ai.

## Overview

Tailscale provides a secure mesh VPN that solves NAT traversal issues common with vast.ai instances while enabling seamless service-to-service communication.

## Quick Start

### 1. Get Tailscale OAuth Credentials

1. Visit [Tailscale Admin Console](https://login.tailscale.com/admin/settings/oauth)
2. Click "Generate OAuth Client"
3. Set scopes: **Devices (Write)**
4. Note down `Client ID` and `Client Secret`

### 2. Deploy Tailscale Operator

```bash
# Create OAuth secret
cp k8s/tailscale/tailscale-secret.yaml.example k8s/tailscale/tailscale-secret.yaml
# Edit and add your OAuth credentials
nano k8s/tailscale/tailscale-secret.yaml

# Deploy operator
kubectl apply -f k8s/tailscale/tailscale-operator.yaml
kubectl apply -f k8s/tailscale/tailscale-secret.yaml

# Check operator status
kubectl get pods -n tailscale
```

### 3. Expose Services via Tailscale

```bash
# Apply Tailscale annotations to orchestrator service
kubectl apply -f k8s/tailscale/june-orchestrator-tailscale.yaml

# Apply Tailscale annotations to LiveKit service  
kubectl apply -f k8s/tailscale/livekit-tailscale.yaml

# Check Tailscale services
kubectl get services -n june-services -o wide
```

### 4. Configure External GPU Service

```bash
# Install Tailscale on vast.ai instance
curl -fsSL https://tailscale.com/install.sh | sh

# Connect to your tailnet
sudo tailscale up

# Verify connectivity
ping june-orchestrator.june-tailnet
ping livekit.june-tailnet
```

## Service Endpoints

Once configured, your services will be available via Tailscale hostnames:

- **Orchestrator**: `http://june-orchestrator.june-tailnet:8080`
- **LiveKit**: `ws://livekit.june-tailnet:7880` (WebSocket)
- **LiveKit**: `http://livekit.june-tailnet:7880` (HTTP)

## Configuration Files

- `tailscale-operator.yaml`: Main operator deployment
- `tailscale-secret.yaml.example`: OAuth credentials template
- `june-orchestrator-tailscale.yaml`: Orchestrator service with Tailscale
- `livekit-tailscale.yaml`: LiveKit service with Tailscale
- `june-gpu-multi-config.yaml`: External service configuration

## Security Notes

- OAuth credentials are stored as Kubernetes secrets
- All traffic is encrypted end-to-end
- Services are only accessible within your tailnet
- Use ACL policies for additional access control

## Troubleshooting

```bash
# Check operator logs
kubectl logs -n tailscale deployment/operator

# Check service annotations
kubectl describe service june-orchestrator -n june-services

# List Tailscale devices
tailscale status

# Test connectivity from external service
telnet june-orchestrator.june-tailnet 8080
```

## Advanced Configuration

### Custom Hostnames

To use custom hostnames, add the annotation:

```yaml
annotations:
  tailscale.com/hostname: "custom-name"
```

### ACL Policies

Configure access control in [Tailscale Admin Console](https://login.tailscale.com/admin/acls):

```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["tag:k8s"],
      "dst": ["tag:k8s:*"]
    }
  ],
  "tagOwners": {
    "tag:k8s": ["your-email@domain.com"]
  }
}
```