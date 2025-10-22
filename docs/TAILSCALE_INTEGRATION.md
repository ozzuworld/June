# Tailscale Integration for June Platform

This document explains how the June platform uses Tailscale (via headscale) to enable secure communication between Kubernetes services and external GPU instances running on vast.ai.

## Overview

The June platform uses a hybrid architecture where:
- **Core services** (orchestrator, LiveKit, auth) run in a main Kubernetes cluster
- **GPU-intensive services** (STT, TTS) run on vast.ai instances for cost efficiency
- **Headscale VPN** provides secure, encrypted communication between all components

## Architecture Diagram

```
┌─────────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐
│   Kubernetes        │    │     Headscale        │    │    Vast.ai GPU      │
│                     │    │   VPN Controller     │    │    Instance         │
│ ┌─────────────────┐ │    │                      │    │                     │
│ │ june-orchestrator│ ├────┤  headscale.ozzu.    ├────┤ june-gpu-multi      │
│ │      :8080      │ │    │      world           │    │  (STT+TTS)          │
│ └─────────────────┘ │    │                      │    │                     │
│ ┌─────────────────┐ │    │  ┌─────────────────┐ │    │ ┌─────────────────┐ │
│ │    livekit      │ ├────┤  │   MagicDNS      │ ├────┤ │ tailscale client│ │
│ │     :7880       │ │    │  │ tail.ozzu.world │ │    │ │                 │ │
│ └─────────────────┘ │    │  └─────────────────┘ │    │ └─────────────────┘ │
└─────────────────────┘    └──────────────────────┘    └─────────────────────┘
     100.64.x.x                 Control Plane              100.64.x.y
```

## Components

### 1. Headscale Server (`headscale.ozzu.world`)
- **Location**: Kubernetes cluster (`headscale` namespace)
- **Purpose**: Self-hosted Tailscale control plane
- **Network**: `100.64.0.0/10` (Tailscale IP range)
- **DNS**: `tail.ozzu.world` (MagicDNS base domain)

### 2. Kubernetes Services (Tailscale Clients)
- **june-orchestrator**: Main AI orchestration service
- **livekit**: WebRTC media server for real-time communication
- **Services exposure**: Via Tailscale operator or sidecar containers

### 3. GPU Services (External Tailscale Client)
- **june-gpu-multi**: Combined STT+TTS service
- **Deployment**: Vast.ai instances via Virtual Kubelet
- **Connection**: Automatic headscale VPN connection on startup

## Setup Process

### Prerequisites

1. **Headscale deployed and accessible**:
   ```bash
   kubectl get deployment -n headscale headscale
   curl -k https://headscale.ozzu.world/health
   ```

2. **Virtual Kubelet for vast.ai configured**:
   ```bash
   kubectl get deployment -n kube-system virtual-kubelet-vast
   kubectl get node vast-gpu-node-python
   ```

3. **Vast.ai API credentials configured**:
   ```bash
   kubectl get secret -n kube-system vast-credentials
   ```

### Installation

1. **Run the setup script**:
   ```bash
   chmod +x scripts/setup-tailscale-integration.sh
   ./scripts/setup-tailscale-integration.sh
   ```

2. **Deploy GPU services**:
   ```bash
   kubectl apply -f k8s/vast-gpu/gpu-services-deployment.yaml
   ```

3. **Monitor deployment**:
   ```bash
   kubectl get pods -n june-services -l app=june-gpu-services -w
   ```

## How It Works

### 1. GPU Service Startup Sequence

1. **Virtual Kubelet** provisions vast.ai GPU instance
2. **Docker container** starts with june-gpu-multi image
3. **start-services.sh** script runs Tailscale connection:
   ```bash
   /app/tailscale-connect.sh &  # Connect to headscale VPN
   sleep 10                     # Wait for connection
   /usr/bin/supervisord         # Start STT+TTS services
   ```

### 2. Tailscale Connection Process

1. **tailscaled daemon** starts in background
2. **tailscale up** connects using pre-auth key:
   ```bash
   tailscale up \
     --login-server=https://headscale.ozzu.world \
     --authkey=$TAILSCALE_AUTH_KEY \
     --hostname=june-gpu-$(hostname | cut -c1-8) \
     --accept-routes \
     --accept-dns
   ```
3. **MagicDNS resolution** enables service discovery:
   - `june-orchestrator:8080` → Kubernetes service
   - `livekit:7880` → Kubernetes service

### 3. Service Communication

```
STT Service (vast.ai) → Webhook → june-orchestrator:8080 (K8s)
                                        ↓
TTS Service (vast.ai) ← API Call ← AI Processing (K8s)
       ↓
LiveKit :7880 (K8s) ← Audio Stream ← Audio Generation
```

## Configuration Files

### Key Files Created

- **`k8s/tailscale/tailscale-auth-secret.yaml`**: Pre-auth key for headscale
- **`June/services/june-gpu-multi/tailscale-connect.sh`**: Auto-connection script
- **`June/services/june-gpu-multi/Dockerfile`**: Updated with Tailscale client
- **`k8s/vast-gpu/gpu-services-deployment.yaml`**: Deployment with Tailscale env vars

### Environment Variables

```yaml
TAILSCALE_AUTH_KEY: "c84a3153377c4b39d2e4f720690786534560430110f08489"
TAILSCALE_LOGIN_SERVER: "https://headscale.ozzu.world"
ORCHESTRATOR_URL: "http://june-orchestrator:8080"
LIVEKIT_WS_URL: "ws://livekit:7880"
```

## Networking Details

### IP Address Allocation
- **Headscale range**: `100.64.0.0/10`
- **Kubernetes services**: `100.64.x.x` (assigned by headscale)
- **GPU instances**: `100.64.y.y` (assigned by headscale)

### DNS Resolution
- **MagicDNS enabled**: `tail.ozzu.world`
- **Service hostnames**: 
  - `june-orchestrator.tail.ozzu.world` → `100.64.x.x`
  - `livekit.tail.ozzu.world` → `100.64.x.x`
- **Short names work**: `june-orchestrator` (no FQDN needed)

### Firewall & Security
- **Encrypted tunnels**: All traffic encrypted via WireGuard
- **No public exposure**: Services only accessible within tailnet
- **Automatic key rotation**: Ephemeral keys expire automatically
- **Network isolation**: Each service gets unique Tailscale IP

## Troubleshooting

### 1. Check Headscale Connectivity

```bash
# Test headscale server
curl -k https://headscale.ozzu.world/health

# List connected nodes
kubectl -n headscale exec deployment/headscale -- headscale nodes list

# Check headscale logs
kubectl logs -n headscale deployment/headscale
```

### 2. Debug GPU Service Connection

```bash
# Check pod status
kubectl get pods -n june-services -l app=june-gpu-services

# View container logs
kubectl logs -n june-services deployment/june-gpu-services

# Check Tailscale status inside container
kubectl exec -n june-services deployment/june-gpu-services -- tailscale status
```

### 3. Network Connectivity Tests

```bash
# From GPU service to orchestrator
kubectl exec -n june-services deployment/june-gpu-services -- \
  curl -v http://june-orchestrator:8080/healthz

# From GPU service to LiveKit
kubectl exec -n june-services deployment/june-gpu-services -- \
  curl -v http://livekit:7880
```

### 4. Virtual Kubelet Issues

```bash
# Check Virtual Kubelet status
kubectl get deployment -n kube-system virtual-kubelet-vast
kubectl logs -n kube-system deployment/virtual-kubelet-vast

# Check virtual node
kubectl get node vast-gpu-node-python
kubectl describe node vast-gpu-node-python
```

### Common Issues

1. **"User not found"** in headscale:
   ```bash
   kubectl -n headscale exec deployment/headscale -- headscale users create ozzu
   ```

2. **Tailscale connection timeout**:
   - Check headscale server accessibility
   - Verify pre-auth key is valid and not expired
   - Check container has NET_ADMIN capabilities

3. **Services unreachable**:
   - Verify Tailscale operator is exposing K8s services
   - Check MagicDNS configuration in headscale
   - Test with explicit Tailscale IPs instead of hostnames

4. **GPU instance not provisioning**:
   - Check vast.ai API credentials
   - Verify Virtual Kubelet logs for errors
   - Check price limits and GPU availability

## Security Considerations

### Best Practices

1. **Rotate auth keys regularly**:
   ```bash
   kubectl -n headscale exec deployment/headscale -- \
     headscale preauthkeys create --user ozzu --reusable --ephemeral
   ```

2. **Use ephemeral keys**: Nodes auto-expire when disconnected

3. **Monitor connected devices**:
   ```bash
   kubectl -n headscale exec deployment/headscale -- headscale nodes list
   ```

4. **Implement ACL policies** in headscale config for access control

5. **Regular security updates**: Keep Tailscale client updated in Docker images

## Performance

### Latency Impact
- **Overhead**: ~5-10ms additional latency via VPN
- **Encryption**: Negligible performance impact on modern hardware
- **Bandwidth**: No throughput degradation for typical AI workloads

### Optimization Tips
- Use geographically close vast.ai instances
- Configure DERP servers for optimal routing
- Monitor connection quality via `tailscale status`

## Monitoring & Observability

### Key Metrics
- **Connection status**: `tailscale status`
- **Network latency**: `ping june-orchestrator`
- **Service health**: HTTP health checks via Tailscale network
- **Headscale metrics**: Exposed on port 50480

### Logging
- **Tailscale logs**: In container stdout/stderr
- **Headscale logs**: `kubectl logs -n headscale deployment/headscale`
- **Virtual Kubelet**: `kubectl logs -n kube-system deployment/virtual-kubelet-vast`

This integration provides a robust, secure, and scalable solution for connecting your Kubernetes-based AI orchestration with cost-effective GPU resources on vast.ai.
