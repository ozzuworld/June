# Janus WebRTC Gateway Deployment Guide

## Changes Made

We've updated the Janus configuration to use a more reliable Docker image and support your custom TURN/STUN server:

### Updated Files:
- `helm/june-platform/values.yaml` - Updated Janus configuration
- `helm/june-platform/templates/configmaps.yaml` - Added custom TURN/STUN support
- `helm/june-platform/templates/june-janus.yaml` - Updated deployment configuration
- `June/services/june-janus/Dockerfile` - Changed to swmansion/janus-gateway

## Before Deploying

### 1. Update Your TURN/STUN Server Details

Edit `helm/june-platform/values.yaml` and replace these placeholders:

```yaml
janus:
  turn:
    enabled: true
    server: "your-turn-server.domain.com"  # REPLACE WITH YOUR TURN SERVER
    port: 3478
    username: "your-turn-username"  # REPLACE WITH YOUR TURN USERNAME
    password: "your-turn-password"  # REPLACE WITH YOUR TURN PASSWORD
```

### 2. Optional: Build New Docker Image (if you made changes)

If you want to use your custom Docker image:

```bash
# Build the new image
docker build -t ozzuworld/june-janus:latest June/services/june-janus/

# Push to your registry
docker push ozzuworld/june-janus:latest

# Update values.yaml to use your image
# Change repository from 'swmansion/janus-gateway' to 'ozzuworld/june-janus'
```

## Deployment Commands

### 1. Deploy/Upgrade with Helm

```bash
# Navigate to your helm directory
cd helm/june-platform

# Update your deployment
helm upgrade june-platform . \
  --namespace june-platform \
  --create-namespace \
  --set secrets.geminiApiKey="your-gemini-key" \
  --set secrets.cloudflareToken="your-cloudflare-token"
```

### 2. Verify Deployment

```bash
# Check pod status
kubectl get pods -n june-platform

# Check Janus logs
kubectl logs -f deployment/june-janus -n june-platform

# Test Janus info endpoint
kubectl port-forward svc/june-janus 8088:8088 -n june-platform
# Then visit: http://localhost:8088/janus/info
```

### 3. Troubleshooting

```bash
# Check configmaps
kubectl get configmaps june-janus-config -n june-platform -o yaml

# Check service
kubectl get svc june-janus -n june-platform

# Describe pod for detailed info
kubectl describe pod -l app=june-janus -n june-platform
```

## Key Improvements

1. **Reliable Docker Image**: Changed from `canyan/janus-gateway` to `swmansion/janus-gateway:0.14.4-0`
2. **Custom TURN/STUN Support**: Added configuration for your own TURN/STUN server
3. **Better Health Checks**: Uses `/janus/info` endpoint instead of TCP checks
4. **Stable Version**: Pinned to specific version instead of `latest`
5. **Proper Environment Variables**: Configured for swmansion image standards

## Configuration Options

### Using Your Own TURN/STUN Server

Set `janus.turn.enabled: true` in values.yaml and provide your server details.

### Fallback to STUNner

Set `janus.turn.enabled: false` and uncomment the stunner section in values.yaml.

### Using Your Own Janus Image

Change the `janus.image.repository` in values.yaml to your custom image.

## Next Steps

1. Replace the placeholder TURN/STUN values with your actual server details
2. Deploy using the helm commands above
3. Test WebRTC functionality
4. Monitor logs for any issues

The new configuration should be much more stable and work better with your custom TURN/STUN setup!