# Tailscale Sidecars for June Platform

This document explains how to deploy June Platform services with Tailscale sidecars for private network access via your self-hosted Headscale server.

## Overview

Tailscale sidecars enable your June Platform services to join your private Tailscale network (tailnet) managed by Headscale. This provides:

- **Private network access** to services without exposing them publicly
- **Zero-trust networking** with automatic authentication and encryption
- **Service discovery** via MagicDNS (e.g., `june-orchestrator.tail.ozzu.world`)
- **Compatibility with existing deployments** - all public access continues to work

## Architecture

Each service gets a Tailscale sidecar container that:
- Runs alongside your main application container
- Uses userspace networking for better security
- Connects to your Headscale server at `https://headscale.ozzu.world`
- Uses pre-authentication keys for automatic registration
- Exposes services on your private tailnet via MagicDNS

## Prerequisites

1. **Headscale server** deployed and accessible
2. **June Platform** already deployed via Helm
3. **Headscale admin access** to create users and auth keys

## Quick Start

### 1. Enable in Configuration

Add to your `config.env`:

```bash
# Headscale Configuration
HEADSCALE_DOMAIN=headscale.ozzu.world
ENABLE_TAILSCALE_SIDECARS=true
```

### 2. Deploy with Fresh Installation

For new deployments, sidecars are automatically included:

```bash
sudo ./scripts/install-orchestrator.sh
```

### 3. Add to Existing Deployment

For existing June Platform deployments:

```bash
# Generate auth keys and deploy sidecars
./scripts/deploy-headscale-sidecars.sh
```

### 4. Verify Deployment

```bash
# Check sidecar pods
kubectl get pods -n june-services

# Check Headscale registrations
kubectl -n headscale exec deployment/headscale -c headscale -- headscale nodes list

# Check sidecar logs
kubectl logs -n june-services deployment/june-orchestrator -c tailscale
```

## Service Access

After deployment, services are accessible via:

### Private Network (Tailscale)
- `june-orchestrator.tail.ozzu.world` - Main API
- `june-idp.tail.ozzu.world` - Keycloak authentication

### Public Network (Unchanged)
- `https://api.ozzu.world` - Main API
- `https://idp.ozzu.world` - Keycloak authentication

### Internal Network (Unchanged)
- `june-orchestrator.june-services.svc.cluster.local` - Kubernetes internal
- `june-idp.june-services.svc.cluster.local` - Kubernetes internal

## Manual Configuration

### Option 1: Using Helm Override

```bash
# Deploy with sidecars enabled
helm upgrade --install june-platform ./helm/june-platform \
  --namespace june-services \
  -f ./helm/june-platform/values-headscale.yaml
```

### Option 2: Using Helm Set Flags

```bash
# Deploy with sidecars via command line
helm upgrade --install june-platform ./helm/june-platform \
  --namespace june-services \
  --set tailscale.enabled=true \
  --set tailscale.controlUrl="https://headscale.ozzu.world"
```

### Option 3: Manual Secret Creation

If you need to create auth keys manually:

```bash
# 1. Connect to Headscale
kubectl -n headscale exec -it deployment/headscale -c headscale -- /bin/sh

# 2. Create users
headscale users create june-orchestrator
headscale users create june-idp

# 3. Generate auth keys
headscale --user june-orchestrator preauthkeys create --reusable --expiration 180d
headscale --user june-idp preauthkeys create --reusable --expiration 180d

# 4. Create secret with your keys
kubectl create secret generic headscale-auth-keys -n june-services \
  --from-literal=june-orchestrator-authkey="tskey-auth-YOUR_KEY_HERE" \
  --from-literal=june-idp-authkey="tskey-auth-YOUR_KEY_HERE"
```

## Configuration Options

### Helm Values

In `helm/june-platform/values.yaml` or override files:

```yaml
tailscale:
  enabled: false  # Set to true to enable sidecars
  controlUrl: "https://headscale.ozzu.world"
  userspace: true  # Use userspace networking
  image: "ghcr.io/tailscale/tailscale:latest"
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi
  # Secret key names (must match auth secret)
  authKeyRefs:
    orchestrator: "june-orchestrator-authkey"
    idp: "june-idp-authkey"
```

### Environment Variables

In `config.env`:

```bash
# Enable sidecars in install orchestrator
ENABLE_TAILSCALE_SIDECARS=true

# Headscale server configuration
HEADSCALE_DOMAIN=headscale.ozzu.world
HEADSCALE_NAMESPACE=headscale
```

## Troubleshooting

### Common Issues

#### Sidecars Not Starting

```bash
# Check pod status
kubectl get pods -n june-services

# Check sidecar logs
kubectl logs -n june-services deployment/june-orchestrator -c tailscale

# Common issues:
# - Invalid auth key (expired or wrong format)
# - Headscale server unreachable
# - Secret missing or wrong key names
```

#### Services Not Registering

```bash
# Check Headscale server status
kubectl get pods -n headscale

# Check node list
kubectl -n headscale exec deployment/headscale -c headscale -- headscale nodes list

# Check auth key validity
kubectl get secret headscale-auth-keys -n june-services -o yaml
```

#### DNS Resolution Issues

```bash
# Test MagicDNS resolution
nslookup june-orchestrator.tail.ozzu.world

# Check if your client is connected to the tailnet
tailscale status

# Verify Headscale DNS configuration
kubectl -n headscale get configmap headscale-config -o yaml
```

### Debug Commands

```bash
# Restart sidecars
kubectl rollout restart deployment/june-orchestrator -n june-services
kubectl rollout restart deployment/june-idp -n june-services

# Check sidecar connectivity
kubectl exec -n june-services deployment/june-orchestrator -c tailscale -- tailscale status

# Force re-authentication
kubectl exec -n june-services deployment/june-orchestrator -c tailscale -- tailscale logout
kubectl exec -n june-services deployment/june-orchestrator -c tailscale -- tailscale up --login-server=https://headscale.ozzu.world --authkey=NEW_KEY
```

## Security Considerations

### Userspace Networking
Sidecars run in userspace mode, which:
- Doesn't require privileged containers
- Provides better isolation
- Reduces attack surface
- Works in restricted environments

### Authentication Keys
- Keys are stored as Kubernetes secrets
- Keys are reusable and have 180-day expiration
- Each service has its own Headscale user
- Keys can be rotated without service downtime

### Network Isolation
- Sidecars only access the tailnet
- Main containers continue normal networking
- No changes to existing service discovery
- Public access remains unchanged

## Integration with Install Orchestrator

The sidecars are integrated into the main installation workflow:

- **Phase 11**: Deploy Headscale server
- **Phase 11.2**: Deploy Tailscale sidecars (new)
- **Phase 11.5**: Connect host node to tailnet

To skip sidecars during installation:

```bash
sudo ./scripts/install-orchestrator.sh --skip 11.2-headscale-sidecars
```

## Rollback and Cleanup

### Disable Sidecars

```bash
# Disable via Helm
helm upgrade june-platform ./helm/june-platform \
  --namespace june-services \
  --set tailscale.enabled=false
```

### Remove Registrations

```bash
# Remove nodes from Headscale
kubectl -n headscale exec deployment/headscale -c headscale -- \
  headscale nodes delete --identifier june-orchestrator

kubectl -n headscale exec deployment/headscale -c headscale -- \
  headscale nodes delete --identifier june-idp
```

### Clean Up Secrets

```bash
# Remove auth keys secret
kubectl delete secret headscale-auth-keys -n june-services
```

## Extending to Other Services

To add sidecars to additional services (STT, TTS, etc.):

1. **Update Helm templates** with sidecar configuration
2. **Add auth key references** in values.yaml
3. **Generate additional auth keys** in deployment script
4. **Update documentation** and examples

Example for STT service:

```yaml
# In helm/june-platform/templates/june-stt.yaml
{{- if and .Values.stt.enabled .Values.tailscale.enabled }}
- name: tailscale
  # ... same sidecar config as orchestrator
  env:
  - name: TS_AUTHKEY
    valueFrom:
      secretKeyRef:
        name: headscale-auth-keys
        key: {{ .Values.tailscale.authKeyRefs.stt }}
  - name: TS_HOSTNAME
    value: "june-stt"
{{- end }}
```

## Support

For issues or questions:

1. Check the troubleshooting section above
2. Review logs from sidecars and Headscale
3. Verify network connectivity and DNS resolution
4. Test with minimal configuration first

The implementation preserves all existing functionality while adding private network access as an optional feature.