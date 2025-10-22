# Headscale Self-Hosted VPN

Self-hosted Tailscale control plane running in your Kubernetes cluster.

## Quick Deploy

```bash
# Apply all manifests
kubectl apply -f k8s/headscale/

# Create user and preauth key
kubectl -n headscale exec -it deploy/headscale -- headscale users create ozzu
kubectl -n headscale exec -it deploy/headscale -- headscale preauthkeys create --user ozzu --reusable --ephemeral
```

## Join Devices

```bash
# Install Tailscale client, then join your mesh:
sudo tailscale up --login-server https://headscale.ozzu.world --authkey <PREAUTH_KEY> --hostname <device-name>
```

## Management

```bash
# List connected devices
kubectl -n headscale exec -it deploy/headscale -- headscale nodes list

# Create new preauth keys
kubectl -n headscale exec -it deploy/headscale -- headscale preauthkeys create --user ozzu --reusable --ephemeral

# Check logs
kubectl -n headscale logs deploy/headscale -f
```

## Files

- **headscale-all.yaml** - Complete deployment (config, service, ingress)
- **README.md** - This guide

**Access:** https://headscale.ozzu.world
