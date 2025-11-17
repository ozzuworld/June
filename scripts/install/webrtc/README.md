# WebRTC Installation Scripts

This directory contains installation scripts for WebRTC components (STUNner and LiveKit) used for real-time communication in the June platform.

## Components

### 01-stunner.sh
Installs STUNner, a Kubernetes-native TURN server that provides NAT traversal for WebRTC connections.

**What it does:**
- Installs Gateway API CRDs (experimental channel for UDPRoute support)
- Deploys STUNner operator to `stunner-system` namespace
- Creates STUNner gateway in `stunner` namespace
- Configures TURN server on UDP port 3478
- Sets up GCP firewall rules (if running on GCP)

**Namespace:** `stunner-system` (operator), `stunner` (gateway)

### 02-livekit.sh
Installs LiveKit, an open-source WebRTC SFU (Selective Forwarding Unit) for scalable real-time video/audio.

**What it does:**
- Deploys LiveKit server to `media-stack` namespace
- Configures TURN server integration with STUNner
- Creates UDP service for WebRTC traffic
- Sets up UDPRoute for STUNner → LiveKit routing
- Creates ReferenceGrant for cross-namespace access
- Generates and saves API credentials

**Namespace:** `media-stack`

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Internet                             │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        │ UDP:3478 (TURN)
                        ▼
                ┌───────────────┐
                │   STUNner     │  (stunner namespace)
                │   Gateway     │
                └───────┬───────┘
                        │ UDPRoute
                        │ (cross-namespace)
                        ▼
                ┌───────────────┐
                │   LiveKit     │  (media-stack namespace)
                │   Server      │
                └───────────────┘
```

## Installation

Run via the orchestrator (recommended):
```bash
sudo ./scripts/install-orchestrator.sh
```

Or manually in order:
```bash
# 1. Install STUNner first
sudo ./scripts/install/webrtc/01-stunner.sh

# 2. Install LiveKit (requires media-stack namespace to exist)
sudo ./scripts/install/webrtc/02-livekit.sh
```

## Configuration

### STUNner
- **TURN Port:** 3478 (UDP)
- **Authentication:** Static (username/password from config.env)
- **Public IP:** Auto-detected
- **Namespace:** `stunner` (gateway), `stunner-system` (operator)

### LiveKit
- **RTC Ports:**
  - TCP: 7881
  - UDP: 7882
  - Port Range: 50000-60000
- **API Credentials:** Stored in `/config/credentials/livekit-credentials.yaml`
- **Server URL:** `http://livekit-livekit-server.media-stack.svc.cluster.local`
- **Namespace:** `media-stack`

## Cross-Namespace Communication

LiveKit (in `media-stack`) and STUNner (in `stunner`) communicate via:

1. **UDPRoute** - Created in `stunner` namespace, routes to LiveKit service
2. **ReferenceGrant** - Created in `media-stack` namespace, allows STUNner to reference LiveKit service

This setup allows clean namespace separation while maintaining connectivity.

## Verification

### STUNner
```bash
# Check STUNner operator
kubectl get pods -n stunner-system

# Check gateway
kubectl get gateway -n stunner

# Check gateway status
kubectl describe gateway stunner-gateway -n stunner
```

### LiveKit
```bash
# Check LiveKit pod
kubectl get pods -n media-stack -l app.kubernetes.io/name=livekit-server

# Check service
kubectl get svc -n media-stack -l app.kubernetes.io/name=livekit-server

# Check UDPRoute
kubectl get udproute -n stunner

# Check ReferenceGrant
kubectl get referencegrant -n media-stack
```

## Testing TURN Server

```bash
# Get external IP
EXTERNAL_IP=$(curl -s ifconfig.me)

# Test with turnutils-stunclient (if installed)
turnutils_stunclient -p 3478 $EXTERNAL_IP

# Or check from LiveKit logs
kubectl logs -n media-stack -l app.kubernetes.io/name=livekit-server
```

## Troubleshooting

### STUNner gateway not programmed
```bash
# Check gateway class
kubectl get gatewayclass

# Check gateway config
kubectl get gatewayconfig -n stunner-system

# Check operator logs
kubectl logs -n stunner-system deployment/stunner-gateway-operator-controller-manager
```

### LiveKit can't connect to TURN
```bash
# Verify TURN configuration in LiveKit
kubectl get deployment livekit-livekit-server -n media-stack -o yaml | grep -A 10 turn_servers

# Check UDPRoute exists and points to correct service
kubectl describe udproute livekit-udp-route -n stunner

# Verify ReferenceGrant allows access
kubectl get referencegrant stunner-to-media-stack -n media-stack
```

### Firewall issues
```bash
# Verify GCP firewall rule (if on GCP)
gcloud compute firewall-rules describe allow-turn-server

# Test UDP connectivity
nc -u -v <EXTERNAL_IP> 3478
```

## Environment Variables

Required in `config.env`:
- `DOMAIN` - Base domain (e.g., ozzu.world)
- `TURN_USERNAME` - TURN server username (default: june-user)
- `STUNNER_PASSWORD` - TURN server password (default: Pokemon123!)

## API Credentials

LiveKit credentials are saved to:
- YAML: `config/credentials/livekit-credentials.yaml`
- ENV: `config/credentials/livekit.env` (if using old scripts)

Default credentials (change in production):
- **API Key:** devkey
- **API Secret:** bbUEBtMjPHrvdZwFEwcpPDJkePL5yTrJ
