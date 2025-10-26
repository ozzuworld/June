# Headscale Sidecar Integration Guide

## Overview

This guide explains how to integrate Tailscale sidecars with your June services using your self-hosted Headscale server. Since the Tailscale Kubernetes operator only works with Tailscale's cloud service, we use Tailscale client containers as sidecars that connect to your Headscale deployment.

## Architecture

Each service gets a Tailscale sidecar container that:
- Runs the Tailscale client in userspace networking mode
- Connects to your Headscale server at `https://headscale.ozzu.world`
- Uses pre-authentication keys for automatic registration
- Exposes services via Tailscale Serve on your private network

## Quick Start

### Automated Deployment

The easiest way to deploy is using the provided script:

```bash
# Make the script executable
chmod +x scripts/deploy-headscale-sidecars.sh

# Run the deployment script
./scripts/deploy-headscale-sidecars.sh
```

This script will:
1. Create Headscale users for each service
2. Generate pre-authentication keys
3. Create Kubernetes secrets
4. Deploy services with sidecars
5. Verify the deployment

### Manual Setup

If you prefer manual setup, follow these steps:

#### 1. Create Headscale Users

```bash
# Connect to your headscale pod
kubectl -n headscale exec -it deployment/headscale -c headscale -- /bin/sh

# Create users for each service
headscale users create june-orchestrator
headscale users create june-idp
headscale users create livekit
headscale users create june-gpu-services
```

#### 2. Generate Pre-Auth Keys

```bash
# Generate reusable keys (save these outputs!)
headscale --user june-orchestrator preauthkeys create --reusable --expiration 180d
headscale --user june-idp preauthkeys create --reusable --expiration 180d
headscale --user livekit preauthkeys create --reusable --expiration 180d
headscale --user june-gpu-services preauthkeys create --reusable --expiration 180d
```

#### 3. Update Secret with Your Keys

Edit `k8s/june-services/deployments/headscale-auth-secrets.yaml` with your generated keys:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: headscale-auth-keys
  namespace: june-services
type: Opaque
stringData:
  orchestrator-authkey: "tskey-auth-YOUR_ORCHESTRATOR_KEY"
  idp-authkey: "tskey-auth-YOUR_IDP_KEY"
  livekit-authkey: "tskey-auth-YOUR_LIVEKIT_KEY"
  gpu-services-authkey: "tskey-auth-YOUR_GPU_SERVICES_KEY"
```

Then apply:
```bash
kubectl apply -f k8s/june-services/deployments/headscale-auth-secrets.yaml
```

#### 4. Deploy Services

```bash
# Deploy orchestrator with sidecar
kubectl apply -f k8s/june-services/deployments/june-orchestrator-headscale.yaml

# Deploy IDP with sidecar
kubectl apply -f k8s/june-services/deployments/june-idp-headscale.yaml

# Deploy GPU services (updated with sidecar)
kubectl apply -f k8s/june-services/deployments/june-gpu-services.yaml

# For LiveKit, if using Helm:
helm upgrade livekit ./helm/livekit -n june-services -f k8s/livekit/livekit-values-headscale.yaml
```

## Service Access

After deployment, your services will be accessible via:

- **june-orchestrator.tail.ozzu.world** - Main orchestrator API
- **june-idp.tail.ozzu.world** - Keycloak authentication server
- **livekit.tail.ozzu.world** - LiveKit WebRTC server
- **june-tts.tail.ozzu.world** - Text-to-speech service
- **june-stt.tail.ozzu.world** - Speech-to-text service

## Verification

### Check Pod Status
```bash
kubectl get pods -n june-services
```

### Check Sidecar Logs
```bash
kubectl logs -n june-services deployment/SERVICE_NAME -c tailscale
```

### Verify Headscale Registration
```bash
kubectl -n headscale exec -it deployment/headscale -c headscale -- headscale nodes list
```

You should see entries for:
- june-orchestrator
- june-idp
- june-gpu-services
- livekit

## Troubleshooting

### Common Issues

#### Sidecar Not Connecting
1. Check auth key is valid and not expired
2. Verify Headscale server is accessible
3. Check sidecar logs for connection errors

#### Services Not Accessible
1. Verify MagicDNS is working: `nslookup june-orchestrator.tail.ozzu.world`
2. Check Tailscale serve status in sidecar
3. Ensure your client device is connected to the same Tailnet

#### Pod Startup Issues
1. Check pod events: `kubectl describe pod POD_NAME -n june-services`
2. Verify secrets exist: `kubectl get secrets -n june-services`
3. Check main container logs

### Log Commands

```bash
# Check deployment status
kubectl get deployments -n june-services

# Check pod details
kubectl describe pod POD_NAME -n june-services

# View sidecar logs
kubectl logs POD_NAME -n june-services -c tailscale

# View main container logs
kubectl logs POD_NAME -n june-services -c CONTAINER_NAME
```

## Security Features

- **Userspace networking**: Sidecars run in userspace mode for better security
- **Minimal privileges**: Containers drop all capabilities except necessary ones
- **Separate users**: Each service has its own Headscale user for access control
- **Key rotation**: Pre-auth keys can be rotated with reasonable expiration times

## Maintenance

### Rotating Auth Keys

```bash
# Generate new key
NEW_KEY=$(kubectl -n headscale exec -it deployment/headscale -c headscale -- headscale --user SERVICE_USER preauthkeys create --reusable --expiration 180d | grep tskey)

# Update secret
kubectl patch secret headscale-auth-keys -n june-services -p "{\"stringData\":{\"SERVICE-authkey\":\"$NEW_KEY\"}}"

# Restart deployment to pick up new key
kubectl rollout restart deployment/SERVICE_NAME -n june-services
```

### Monitoring

```bash
# Check Headscale server status
kubectl get pods -n headscale

# Monitor service connectivity
kubectl -n headscale exec -it deployment/headscale -c headscale -- headscale nodes list
kubectl -n headscale exec -it deployment/headscale -c headscale -- headscale routes list
```

## Files Created

- `k8s/june-services/deployments/headscale-auth-secrets.yaml` - Secret template for auth keys
- `k8s/june-services/deployments/june-orchestrator-headscale.yaml` - Orchestrator with sidecar
- `k8s/june-services/deployments/june-idp-headscale.yaml` - IDP with sidecar
- `k8s/june-services/deployments/june-gpu-services.yaml` - Updated GPU services with sidecar
- `k8s/livekit/livekit-values-headscale.yaml` - LiveKit Helm values with sidecar
- `scripts/deploy-headscale-sidecars.sh` - Automated deployment script
- `docs/HEADSCALE_SETUP.md` - This documentation