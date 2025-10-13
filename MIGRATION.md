# June Platform Migration Guide: Janus → LiveKit

This document explains the migration from the old Janus WebRTC implementation to the new LiveKit + STUNner setup.

## 🔄 What Changed

### Old Architecture (Deprecated)
- **WebRTC Server**: Janus Gateway
- **TURN Integration**: STUNner configured via `install.sh`
- **Deployment**: Single monolithic Helm chart
- **Configuration**: Hardcoded in Helm values

### New Architecture (Current)
- **WebRTC Server**: LiveKit Server
- **TURN Integration**: STUNner with Gateway API
- **Deployment**: Modular approach with separate scripts
- **Configuration**: Kubernetes manifests in `k8s/` directory

## 📂 File Structure Changes

```
/June
├── install-clean.sh          # Core services (no WebRTC)
├── install-livekit.sh         # LiveKit + STUNner setup
├── install.sh                 # Original (contains old Janus code)
├── k8s/
│   ├── livekit/              # LiveKit configuration
│   │   ├── livekit-values.yaml
│   │   └── livekit-udp-svc.yaml
│   └── stunner/              # STUNner configuration
│       ├── 00-namespaces.yaml
│       ├── 10-secret.template.yaml
│       ├── 20-dataplane-hostnet.yaml
│       ├── 30-gatewayconfig.yaml
│       ├── 40-gatewayclass.yaml
│       ├── 50-gateway.yaml
│       └── 60-udproute-livekit.yaml
└── helm/june-platform/
    └── templates/
        └── june-janus.yaml    # REMOVED ❌
```

## 🚀 Migration Steps

### For Fresh Installations

1. **Install Core Services:**
   ```bash
   sudo ./install-clean.sh
   ```

2. **Install WebRTC Services:**
   ```bash
   sudo ./install-livekit.sh
   ```

### For Existing Deployments

1. **Backup Current Setup:**
   ```bash
   kubectl get all -n june-services -o yaml > june-backup.yaml
   kubectl get all -n stunner -o yaml > stunner-backup.yaml
   ```

2. **Remove Old Janus Components:**
   ```bash
   kubectl delete deployment june-janus -n june-services
   kubectl delete service june-janus -n june-services
   kubectl delete ingress june-janus -n june-services
   kubectl delete udproute june-janus-route -n stunner
   ```

3. **Install New LiveKit Setup:**
   ```bash
   sudo ./install-livekit.sh
   ```

4. **Verify Migration:**
   ```bash
   kubectl get pods -n media          # LiveKit pods
   kubectl get gateway -n stunner     # STUNner gateway
   kubectl get udproute -n stunner    # LiveKit route
   ```

## 🔧 Configuration Changes

### STUNner Configuration

**Old (in install.sh):**
- Hardcoded in install script
- Mixed with other installation steps
- Difficult to customize

**New (in k8s/stunner/):**
- Declarative Kubernetes manifests
- Modular and reusable
- Easy to version control

### Authentication

**STUNner Credentials:**
- **Username:** `june-user`
- **Password:** `Pokemon123!`
- **TURN URL:** `turn:<external-ip>:3478`

### LiveKit Configuration

**Service Ports:**
- **API Port:** 80 (HTTP/gRPC)
- **ICE TCP Port:** 7881
- **RTP UDP Port:** 7882

**Namespace:** `media`

## 🏗️ Architecture Benefits

### LiveKit Advantages
- **Better Performance:** Optimized for real-time communication
- **SFU Architecture:** Selective Forwarding Unit for better scalability
- **Modern API:** gRPC-based API with better client SDKs
- **Active Development:** Regular updates and feature additions

### Modular Deployment Benefits
- **Separation of Concerns:** Core services vs WebRTC services
- **Easier Maintenance:** Independent updates and scaling
- **Better Testing:** Individual component testing
- **Flexible Deployment:** Optional WebRTC for non-real-time deployments

## 🧪 Testing the Migration

### 1. Test STUNner Connectivity
```bash
./test-stunner.sh
```

### 2. Verify LiveKit
```bash
kubectl exec -n media deployment/livekit -- /livekit-server --version
```

### 3. Check UDPRoute
```bash
kubectl describe udproute livekit-udp-route -n stunner
```

### 4. Test WebRTC Connection
```bash
# Use LiveKit CLI or SDK to test connection
# TURN server: turn:<external-ip>:3478
# Username: june-user
# Password: Pokemon123!
```

## 📋 Troubleshooting

### Common Issues

1. **STUNner Gateway Not Ready:**
   ```bash
   kubectl describe gateway stunner-gateway -n stunner
   kubectl logs -n stunner-system deployment/stunner-gateway-operator-controller-manager
   ```

2. **LiveKit Connection Failed:**
   ```bash
   kubectl logs -n media deployment/livekit
   kubectl describe svc livekit-udp -n media
   ```

3. **UDPRoute Not Working:**
   ```bash
   kubectl describe udproute livekit-udp-route -n stunner
   # Check if ReferenceGrant exists
   kubectl get referencegrant -n media
   ```

### Debug Commands

```bash
# Check all WebRTC components
kubectl get pods -n media
kubectl get pods -n stunner
kubectl get pods -n stunner-system

# Check networking
kubectl get gateway -A
kubectl get udproute -A
kubectl get svc -n media

# Check logs
kubectl logs -n media deployment/livekit
kubectl logs -n stunner-system deployment/stunner-gateway-operator-controller-manager
```

## 🔄 Rollback Plan

If you need to rollback to the old Janus setup:

1. **Remove LiveKit:**
   ```bash
   helm uninstall livekit -n media
   kubectl delete namespace media
   ```

2. **Remove New STUNner Config:**
   ```bash
   kubectl delete -f k8s/stunner/
   ```

3. **Restore Janus (if needed):**
   ```bash
   # Re-enable Janus in helm/june-platform/values.yaml
   # Set janus.enabled: true
   helm upgrade june-platform ./helm/june-platform -n june-services
   ```

## 📞 Support

If you encounter issues during migration:

1. Check the troubleshooting section above
2. Review logs from all components
3. Verify network connectivity
4. Ensure DNS resolution is working

## 📝 Notes

- The old `install.sh` is preserved for reference but should not be used for new deployments
- Use `install-clean.sh` for core services and `install-livekit.sh` for WebRTC
- Configuration is now versioned in the `k8s/` directory
- LiveKit provides better WebRTC performance and modern APIs