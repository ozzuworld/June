# Headscale Self-Hosted VPN

Self-hosted Tailscale control plane running in your Kubernetes cluster.

## Quick Deploy

```bash
# Apply deployment
kubectl apply -f k8s/headscale/headscale-all.yaml

# Wait for deployment
kubectl -n headscale rollout status deploy/headscale

# Create user and preauth key
kubectl -n headscale exec -it deploy/headscale -- headscale users create ozzu
kubectl -n headscale exec -it deploy/headscale -- headscale preauthkeys create --user ozzu --reusable --ephemeral
```

## SSL Certificate Setup

**Option 1: Use existing wildcard certificate (recommended)**
```bash
# Copy existing wildcard cert to headscale namespace
kubectl get secret ozzu-world-wildcard-tls -n june-services -o yaml | \
  sed 's/namespace: june-services/namespace: headscale/' | \
  sed 's/name: ozzu-world-wildcard-tls/name: headscale-wildcard-tls/' | \
  kubectl apply -f -

# Update ingress to use wildcard cert
kubectl patch ingress headscale-ingress -n headscale --type='json' -p='[
  {"op":"replace","path":"/spec/tls/0/secretName","value":"headscale-wildcard-tls"},
  {"op":"remove","path":"/metadata/annotations/cert-manager.io~1cluster-issuer"}
]'
```

**Option 2: Let cert-manager create new certificate (if letsencrypt-prod ClusterIssuer exists)**
- Certificate will be automatically provisioned via Let's Encrypt

## Join Devices

```bash
# Desktop/Server:
sudo tailscale up --login-server https://headscale.ozzu.world --authkey <PREAUTH_KEY> --hostname <device-name>

# Mobile (iOS/Android):
1. Install Tailscale app
2. Add account with custom server: https://headscale.ozzu.world
3. Enter preauth key
```

## Management

```bash
# List connected devices
kubectl -n headscale exec -it deploy/headscale -- headscale nodes list

# Create new preauth keys
kubectl -n headscale exec -it deploy/headscale -- headscale preauthkeys create --user ozzu --reusable --ephemeral

# Create additional users
kubectl -n headscale exec -it deploy/headscale -- headscale users create <username>

# Check service health
curl https://headscale.ozzu.world/health

# View logs
kubectl -n headscale logs deploy/headscale -f
```

## Files

- **headscale-all.yaml** - Complete deployment (namespace, config, service, ingress)
- **README.md** - This guide

**Access:** https://headscale.ozzu.world (returns 404 - normal, no web UI)
