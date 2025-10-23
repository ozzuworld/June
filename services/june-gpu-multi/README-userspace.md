# June GPU Multi-Service Container with Tailscale Userspace Networking

This container supports **Tailscale userspace networking mode** which works in environments without privileged container access or `/dev/net/tun` device.

## Features

✅ **No privileged containers needed**  
✅ **Works on Vast.ai and other container platforms**  
✅ **SOCKS5 and HTTP proxy support**  
✅ **Automatic Headscale/Tailscale connectivity**  
✅ **GPU-accelerated STT and TTS services**

## Quick Start

### 1. Build the Userspace Image

```bash
cd services/june-gpu-multi
docker build -f Dockerfile-userspace -t ozzuworld/june-gpu-userspace:latest .
docker push ozzuworld/june-gpu-userspace:latest
```

### 2. Deploy on Vast.ai

**Environment Variables:**
- `TAILSCALE_AUTH_KEY` = `your-headscale-auth-key`
- `TAILSCALE_LOGIN_SERVER` = `https://headscale.ozzu.world`
- `TAILSCALE_TEST_ENDPOINT` = `http://june-orchestrator.june-services.svc.cluster.local:8080/health`

**Docker Options:** None needed! (No privileged flags required)

### 3. Deploy with Kubernetes + Virtual Kubelet

```bash
# Update Virtual Kubelet
kubectl patch deployment virtual-kubelet-vast-python -n kube-system -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "virtual-kubelet",
          "image": "ozzuworld/virtual-kubelet-vast-python:userspace"
        }]
      }
    }
  }
}'

# Update GPU deployment to use userspace image
kubectl patch deployment june-gpu-services -n june-services -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "june-multi-gpu",
          "image": "ozzuworld/june-gpu-userspace:latest",
          "env": [
            {
              "name": "TAILSCALE_AUTH_KEY",
              "valueFrom": {
                "secretKeyRef": {
                  "name": "tailscale-auth",
                  "key": "TAILSCALE_AUTH_KEY"
                }
              }
            },
            {
              "name": "TAILSCALE_LOGIN_SERVER", 
              "valueFrom": {
                "secretKeyRef": {
                  "name": "tailscale-auth",
                  "key": "TAILSCALE_LOGIN_SERVER"
                }
              }
            }
          ]
        }]
      }
    }
  }
}'

# Scale to 1 to test
kubectl -n june-services scale deploy/june-gpu-services --replicas=1
```

## How It Works

1. **Container starts** with `start-services-userspace.sh`
2. **Tailscale starts** in userspace mode (no `/dev/net/tun` needed)
3. **SOCKS5/HTTP proxy** available on `localhost:1055`
4. **Services use proxy** environment variables:
   - `ALL_PROXY=socks5://localhost:1055/`
   - `HTTP_PROXY=http://localhost:1055/`
5. **STT/TTS services** can reach Kubernetes cluster via VPN

## Logs & Debugging

```bash
# SSH into Vast.ai container
ssh root@<vast-host> -p <port>

# Check Tailscale status
tailscale status

# Test proxy connectivity 
ALL_PROXY=socks5://localhost:1055/ curl http://june-orchestrator.june-services.svc.cluster.local:8080/health

# Check service health
curl http://localhost:8000/healthz  # TTS
curl http://localhost:8001/healthz  # STT
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|----------|
| `TAILSCALE_AUTH_KEY` | Headscale pre-auth key | `c84a315337...` |
| `TAILSCALE_LOGIN_SERVER` | Headscale server URL | `https://headscale.ozzu.world` |
| `TAILSCALE_TEST_ENDPOINT` | Connectivity test URL | `http://june-orchestrator...` |
| `STT_PORT` | STT service port | `8001` |
| `TTS_PORT` | TTS service port | `8000` |

## Benefits of Userspace Mode

- 🔒 **No privileged containers** - works in restricted environments
- 🚀 **Easy deployment** - no special Docker flags needed  
- 🌐 **Universal compatibility** - works on any container platform
- 🔧 **Same functionality** - full VPN connectivity via proxy
- 📊 **Better security** - no elevated container permissions

## Troubleshooting

### Tailscale connection fails
- Check `TAILSCALE_AUTH_KEY` is valid and not expired
- Verify `TAILSCALE_LOGIN_SERVER` is accessible
- Check Headscale server logs

### Services can't reach cluster
- Verify Tailscale status shows connected
- Test proxy: `ALL_PROXY=socks5://localhost:1055/ curl <test-url>`
- Check if cluster services are accessible via Tailscale network

### Container crashes
- Check logs for startup errors
- Verify all required environment variables are set
- Ensure base image `ozzuworld/june-multi-gpu:latest` exists
