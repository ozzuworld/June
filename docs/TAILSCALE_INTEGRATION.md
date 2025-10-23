# Tailscale Integration for June Platform

This document explains how the June platform uses Tailscale userspace networking to enable secure communication between services and external GPU instances.

## Overview

The June platform uses Tailscale in **userspace networking mode** to connect:
- **Core services** (orchestrator, LiveKit) 
- **GPU-intensive services** (STT, TTS) running on vast.ai instances
- **Headscale VPN** provides secure, encrypted communication via SOCKS5/HTTP proxy

## Architecture

```
┌─────────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐
│   Kubernetes        │    │     Headscale        │    │    Vast.ai GPU      │
│                     │    │   VPN Controller     │    │    Instance         │
│ ┌─────────────────┐ │    │                      │    │                     │
│ │ june-orchestrator│ ├────┤  headscale.ozzu.    ├────┤ june-gpu-multi      │
│ │      :8080      │ │    │      world           │    │  (STT+TTS)          │
│ └─────────────────┘ │    │                      │    │                     │
│ ┌─────────────────┐ │    │  ┌─────────────────┐ │    │ ┌─────────────────┐ │
│ │    livekit      │ ├────┤  │   SOCKS5 Proxy  │ ├────┤ │ Userspace       │ │
│ │     :7880       │ │    │  │  localhost:1055 │ │    │ │ tailscaled      │ │
│ └─────────────────┘ │    │  └─────────────────┘ │    │ └─────────────────┘ │
└─────────────────────┘    └──────────────────────┘    └─────────────────────┘
```

## Userspace Networking Mode

**Why userspace mode?**
- No `/dev/net/tun` device required
- No root privileges or NET_ADMIN capability needed
- Works in restricted container environments (vast.ai, cloud platforms)
- Uses SOCKS5 and HTTP proxy for application connectivity

**How it works:**
1. `tailscaled --tun=userspace-networking` starts without TUN device
2. SOCKS5 proxy runs on `localhost:1055`
3. HTTP proxy also available on `localhost:1055`
4. Applications use proxy environment variables for connectivity

## Setup

### 1. Environment Variables

Required in your `.env.tailscale` file:
```bash
TAILSCALE_AUTH_KEY=your-headscale-auth-key
ORCHESTRATE_URL=http://june-orchestrator:8080
LIVEKIT_WS_URL=ws://livekit:7880
```

### 2. Container Deployment

```bash
# Build and push updated container
docker build -f June/services/june-gpu-multi/Dockerfile -t ozzuworld/june-multi-gpu:latest .
docker push ozzuworld/june-multi-gpu:latest

# Deploy to vast.ai
docker run -d --gpus all --env-file .env.tailscale ozzuworld/june-multi-gpu:latest
```

### 3. Expected Startup Logs

✅ **Correct userspace mode logs:**
```
[TAILSCALE] Starting Tailscale in userspace networking mode...
[TAILSCALE] Starting Tailscale daemon with userspace networking...
[TAILSCALE] Userspace networking active with proxies on localhost:1055
```

❌ **Old TUN device errors (should not appear):**
```
tun module not loaded nor found on disk
/dev/net/tun does not exist
Permission denied (you must be root)
```

## Application Integration

### Automatic Proxy Configuration

The `tailscale-connect.sh` script automatically sets:
```bash
export ALL_PROXY=socks5://localhost:1055/
export HTTP_PROXY=http://localhost:1055/
export HTTPS_PROXY=http://localhost:1055/
```

### Python Applications (httpx)

Applications automatically detect proxy settings:
```python
# orchestrator_client.py automatically uses proxy
import httpx
import os

proxy_url = os.getenv('ALL_PROXY')  # socks5://localhost:1055/
client = httpx.AsyncClient(proxies={
    "http://": proxy_url,
    "https://": proxy_url
})
```

## Troubleshooting

### 1. Check Tailscale Status

```bash
# Inside container
tailscale status
tailscale ping june-orchestrator
```

### 2. Test Proxy Connectivity

```bash
# Test SOCKS5 proxy
curl --proxy socks5://localhost:1055 http://june-orchestrator:8080/healthz

# Test HTTP proxy  
curl --proxy http://localhost:1055 http://june-orchestrator:8080/healthz

# Test with environment variables
ALL_PROXY=socks5://localhost:1055/ curl http://june-orchestrator:8080/healthz
```

### 3. Debug Service Connectivity

```bash
# Check if Tailscale daemon is running
ps aux | grep tailscaled

# Check proxy ports
netstat -tlpn | grep 1055

# Test DNS resolution
nslookup june-orchestrator
```

### 4. Common Issues

**Issue: Still seeing TUN device errors**
- Solution: Rebuild container with latest code, old script cached

**Issue: Services can't reach orchestrator**
- Check: `ALL_PROXY` environment variable set
- Test: Direct proxy connection with curl

**Issue: Tailscale won't connect to headscale**
- Check: `TAILSCALE_AUTH_KEY` is valid
- Verify: Headscale server is accessible

**Issue: "tailscaled" not running**
- Check: Container startup logs for script errors
- Verify: Script has execute permissions

## File Structure

**Active files (current implementation):**
- `June/services/june-gpu-multi/tailscale-connect.sh` - Main connection script
- `June/services/june-gpu-multi/start-services.sh` - Container startup
- `June/services/june-gpu-multi/Dockerfile` - Container build
- `June/services/june-gpu-multi/stt/orchestrator_client.py` - Proxy-aware HTTP client

**Environment Variables:**
```bash
TAILSCALE_AUTH_KEY=<headscale-auth-key>
ORCHESTRATE_URL=http://june-orchestrator:8080
LIVEKIT_WS_URL=ws://livekit:7880
```

## Security & Performance

### Security Benefits
- **No privileged containers**: Userspace mode doesn't need root
- **Encrypted tunnels**: All traffic via WireGuard encryption
- **Proxy isolation**: Applications use localhost proxy only

### Performance Characteristics
- **Latency**: ~5-10ms additional overhead via proxy
- **Throughput**: Minimal impact for typical AI workloads
- **Resource usage**: Lower than kernel TUN device mode

## Migration Notes

If migrating from old TUN device mode:
1. **Remove** privileged container settings
2. **Remove** `--cap-add=NET_ADMIN` and `--device=/dev/net/tun`
3. **Update** applications to use proxy environment variables
4. **Test** connectivity via SOCKS5/HTTP proxy

This userspace networking approach provides a more portable and secure solution for Tailscale connectivity in containerized environments.