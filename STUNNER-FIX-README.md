# STUNner Fix: Reliable STUN/TURN Server for June Platform

## Problem Solved

The original STUNner deployment was failing with `ErrImagePull` and `ImagePullBackOff` errors because:

1. **Unreliable STUNner Operator**: The `l7mp/stunner:latest` image was unstable and often failed to start
2. **Complex Gateway Configuration**: The STUNner Gateway Operator added unnecessary complexity
3. **Image Pull Issues**: The official STUNner image had reliability problems

## Solution: Reliable coturn-based STUNner

We've replaced the problematic STUNner operator with a reliable coturn-based TURN server:

- **Stable Image**: Uses `coturn/coturn:4.6.2-alpine` (well-tested, stable)
- **Simple Configuration**: Direct deployment without complex operators
- **Proven Reliability**: coturn is the industry-standard TURN server
- **hostNetwork Support**: Properly configured for bare metal Kubernetes

## Files Updated

### 1. Fixed Kubernetes Manifests
- **`k8s/stunner-manifests.yaml`**: Updated with reliable coturn deployment
- Uses stable coturn image instead of problematic stunner operator
- Simplified configuration without Gateway APIs
- Proper hostNetwork configuration for bare metal

### 2. Fixed Installation Scripts  
- **`scripts/install-k8s/stage3-install-stunner-fixed.sh`**: New reliable installation script
- **`scripts/install-k8s/unified-install-june-platform.sh`**: Updated to use reliable STUNner
- Both scripts now deploy coturn instead of the problematic operator

### 3. Updated GitHub Actions
The deployment workflow automatically uses the fixed configuration when deploying STUNner resources.

## Usage Instructions

### For Fresh Installations

Use the updated unified installer:

```bash
# Download and run the fixed unified installer
sudo chmod +x scripts/install-k8s/unified-install-june-platform.sh
sudo ./scripts/install-k8s/unified-install-june-platform.sh
```

This will:
- Install Kubernetes infrastructure
- Deploy the reliable coturn-based STUNner
- Configure GitHub Actions runner
- Set up all required services

### For Existing Installations

If you have an existing installation with the problematic STUNner:

```bash
# Use the fixed STUNner installation script
sudo chmod +x scripts/install-k8s/stage3-install-stunner-fixed.sh
sudo ./scripts/install-k8s/stage3-install-stunner-fixed.sh
```

This will:
- Clean up the old STUNner operator
- Remove problematic deployments
- Deploy the reliable coturn-based solution
- Verify everything is working

### Manual Fix (if needed)

If you need to manually apply the fix:

```bash
# Delete problematic STUNner resources
kubectl delete deployment june-stunner-gateway -n stunner
kubectl delete pods -n stunner --all

# Apply the fixed manifests
kubectl apply -f k8s/stunner-manifests.yaml

# Verify deployment
kubectl get pods -n stunner -w
netstat -ulnp | grep 3478
```

## Configuration Details

### coturn Configuration

The reliable STUNner now uses these coturn parameters:

```bash
turnserver \
  -n                          # No daemon mode
  -a                          # Use long-term authentication  
  -v                          # Verbose logging
  -L 0.0.0.0                  # Listen on all interfaces
  -p 3478                     # TURN port
  -r your-turn-domain         # Realm
  -u username:password        # Authentication
  --no-dtls --no-tls         # Disable TLS for simplicity
  --min-port=49152           # RTP port range
  --max-port=65535
```

### Deployment Features

- **hostNetwork: true**: Direct host networking for bare metal
- **nodeSelector**: Runs on control plane node
- **Stable Image**: coturn/coturn:4.6.2-alpine
- **Resource Limits**: Reasonable CPU/memory limits
- **Health Checks**: Proper readiness/liveness probes
- **Port Verification**: Checks that port 3478 is actually listening

## Testing the Fix

### 1. Check Deployment Status

```bash
# Check if STUNner pod is running
kubectl get pods -n stunner

# Should show:
NAME                                   READY   STATUS    RESTARTS   AGE
june-stunner-gateway-xxxxxxxxx-xxxxx   1/1     Running   0          2m
```

### 2. Verify Port Binding

```bash
# Check if port 3478 is listening on host
netstat -ulnp | grep 3478

# Should show something like:
udp        0      0 0.0.0.0:3478           0.0.0.0:*         12345/turnserver
```

### 3. Test STUN/TURN Connectivity

```bash
# Use the test script
python3 scripts/test-turn-server.py
```

### 4. External Testing

Use https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/

- **STUN URI**: `stun:your-turn-domain.com:3478`  
- **TURN URI**: `turn:your-turn-domain.com:3478`
- **Username**: `june-user` (or your configured username)
- **Password**: Your configured password

## Troubleshooting

### If STUNner Pod Won't Start

```bash
# Check pod logs
kubectl logs -n stunner -l app=stunner

# Check pod events
kubectl describe pod -n stunner -l app=stunner

# Verify image can be pulled
docker pull coturn/coturn:4.6.2-alpine
```

### If Port 3478 Not Listening

```bash
# Check if something else is using the port
sudo lsof -i :3478

# Kill conflicting processes if needed
sudo kill $(sudo lsof -t -i:3478)

# Restart STUNner deployment
kubectl rollout restart deployment/june-stunner-gateway -n stunner
```

### If Authentication Fails

```bash
# Check the authentication secret
kubectl get secret stunner-auth-secret -n stunner -o yaml

# Verify username/password are correct
kubectl get secret stunner-auth-secret -n stunner -o jsonpath='{.data.username}' | base64 -d
kubectl get secret stunner-auth-secret -n stunner -o jsonpath='{.data.password}' | base64 -d
```

## Why This Fix Works

1. **Proven Technology**: coturn is the industry standard TURN server, used by major WebRTC applications
2. **Simple Deployment**: No complex operators or CRDs, just a standard Kubernetes deployment
3. **Reliable Image**: The coturn Alpine image is well-maintained and stable
4. **Direct Configuration**: Command-line arguments instead of complex YAML configurations
5. **Better Debugging**: Standard logs and familiar coturn configuration

## Migration Path

For existing deployments, the migration is automatic:

1. **GitHub Actions**: Will automatically use the new configuration on next deployment
2. **Manual Deployments**: Use the fixed installation scripts
3. **Configuration Preserved**: All existing settings (username, password, domain) are maintained

## Performance Benefits

- **Faster Startup**: coturn starts much faster than the STUNner operator
- **Lower Resource Usage**: More efficient resource utilization  
- **Better Stability**: Fewer crashes and restarts
- **Improved Logging**: Clearer, more detailed logs for debugging

This fix ensures that your June platform will have reliable STUN/TURN services that work consistently every time you deploy.