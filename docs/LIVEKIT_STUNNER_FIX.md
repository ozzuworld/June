# LiveKit STUNner Connectivity Fix

This document explains the fixes applied to resolve client connectivity issues with LiveKit and STUNner integration.

## Issues Identified

### 1. Missing UDP Service for LiveKit RTC
**Problem**: LiveKit deployment only had TCP services configured, but STUNner's UDPRoute required a UDP service for WebRTC traffic routing.

**Solution**: Added a dedicated UDP service (`livekit-udp`) that exposes LiveKit's RTC UDP traffic on port 7882.

### 2. Incorrect UDPRoute Target
**Problem**: The UDPRoute was pointing to the TCP service on port 7881 instead of a UDP service.

**Solution**: Updated UDPRoute to target the new `livekit-udp` service on port 7882.

### 3. Service Namespace Consistency
**Problem**: UDPRoute was referencing services in different namespaces inconsistently.

**Solution**: Ensured all routes point to `june-services` namespace where LiveKit is deployed.

### 4. STUNner Auth Secret Namespace
**Problem**: STUNner GatewayConfig expects auth secret in `stunner-system` namespace, but deployment scripts were creating it in `stunner` namespace.

**Solution**: Updated deployment scripts to create the auth secret in the correct `stunner-system` namespace.

## Changes Made

### 1. LiveKit Helm Template (`helm/june-platform/templates/livekit.yaml`)
- Added UDP port configuration to LiveKit container
- Created separate UDP service `livekit-udp` on port 7882
- Added STUNner annotation to UDP service
- Maintained backward compatibility with existing TCP services

### 2. Helm Values (`helm/june-platform/values.yaml`)
- Added `rtc.udp_port: 7882` configuration
- Documented the new UDP port setting

### 3. STUNner UDPRoutes
- Updated `k8s/stunner/60-udproute-livekit.yaml` to target `livekit-udp:7882`
- Updated `k8s/stunner/udproute-livekit.yaml` for consistency
- Ensured correct namespace references (`june-services`)

### 4. STUNner Deployment Script (`scripts/deploy-stunner-hostnet.sh`)
- Fixed auth secret creation to use `stunner-system` namespace
- Added better logging and error handling
- Improved success confirmation messages

## Configuration Overview

### LiveKit Services
```yaml
# TCP Service (existing)
livekit-livekit-server:
  ports:
    - 7880 (HTTP)
    - 7881 (RTC TCP)

# UDP Service (new)
livekit-udp:
  ports:
    - 7882 (RTC UDP)
```

### STUNner Configuration
```yaml
# Gateway
stunner-gateway:
  port: 3478 (TURN)
  public_ip: ${PUBIP}

# UDPRoute
livekit-udp-route:
  target: livekit-udp.june-services:7882

# Auth Secret
stunner-auth-secret:
  namespace: stunner-system
  username: june-user
  password: Pokemon123!
```

## Testing the Fix

### 1. Verify Services
```bash
# Check LiveKit services
kubectl get svc -n june-services | grep livekit

# Should show both TCP and UDP services:
# livekit-livekit-server  ClusterIP  ... 7880:7880/TCP,7881:7881/TCP
# livekit-udp             ClusterIP  ... 7882:7882/UDP
```

### 2. Verify STUNner Gateway
```bash
# Check gateway status
kubectl get gateway stunner-gateway -n stunner -o wide

# Should show status: Programmed=True
```

### 3. Verify UDPRoute
```bash
# Check UDPRoute
kubectl get udproute -n stunner -o yaml

# Should target livekit-udp.june-services:7882
```

### 4. Test TURN Server
```bash
# Replace YOUR_PUBLIC_IP with actual server IP
turnutils_uclient -p 3478 -u june-user -w Pokemon123! YOUR_PUBLIC_IP
```

## Deployment Steps

### 1. Deploy the Updated Configuration
```bash
# Update LiveKit deployment
helm upgrade june-platform ./helm/june-platform \
  --namespace june-services \
  --reuse-values

# Update STUNner configuration
kubectl apply -f k8s/stunner/60-udproute-livekit.yaml
```

### 2. Verify Connectivity
```bash
# Check all components
kubectl get pods,svc,gateway,udproute -A | grep -E 'livekit|stunner'
```

### 3. Test Client Connection
- Clients should now be able to connect through the TURN server
- WebRTC traffic should route correctly through STUNner to LiveKit

## Firewall Requirements

Ensure the following ports are open:
- **3478/UDP**: TURN server (STUNner gateway)
- **7882/UDP**: LiveKit RTC traffic (internal, routed via STUNner)

For GCP, the deployment script attempts to create the firewall rule automatically:
```bash
gcloud compute firewall-rules create allow-turn-server \
  --allow udp:3478 \
  --source-ranges 0.0.0.0/0 \
  --description "Allow TURN server on port 3478"
```

## Troubleshooting

If clients still cannot connect:

1. **Check service endpoints**:
   ```bash
   kubectl get endpoints -n june-services | grep livekit
   ```

2. **Verify STUNner logs**:
   ```bash
   kubectl logs -n stunner-system deployment/stunner-gateway-operator-controller-manager
   ```

3. **Check LiveKit logs**:
   ```bash
   kubectl logs -n june-services deployment/livekit-livekit-server
   ```

4. **Test TURN connectivity**:
   ```bash
   # Install TURN client tools
   sudo apt-get install coturn-utils
   
   # Test TURN server
   turnutils_uclient -p 3478 -u june-user -w Pokemon123! YOUR_PUBLIC_IP
   ```

## Backward Compatibility

All changes maintain backward compatibility:
- Existing TCP services continue to work
- Original port configurations are preserved
- Additional UDP service is added without breaking existing functionality
- Helm values have sensible defaults