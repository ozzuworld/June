# June Platform Installation Guide

**New Modular Architecture** - Split installation for better maintainability and debugging.

## 📋 Prerequisites

- **Ubuntu 22.04 LTS** (bare metal or VM)
- **Root access** (all scripts run as root)
- **Minimum 8GB RAM, 4 CPU cores**
- **NVIDIA GPU** (optional, for STT/TTS services)
- **Public IP address** (for LoadBalancer and TURN server)

---

## 🚀 Quick Start (All-in-One)

```bash
# Clone repository
git clone https://github.com/YOUR_REPO/june-platform.git
cd june-platform/scripts/install-k8s

# Run main orchestrator (installs everything)
./install-june-platform.sh
```

The orchestrator will guide you through:
1. ✅ Core infrastructure (Docker, K8s, ingress, cert-manager)
2. ✅ Networking (MetalLB, STUNner with Gateway API v1alpha2)
3. ✅ GPU Operator (optional)
4. ✅ GitHub Actions Runner (optional)
5. ✅ Domain & certificate configuration
6. ✅ Application secrets

---

## 🔧 Modular Installation (Step-by-Step)

For more control, run individual scripts in order:

### **Step 1: Core Infrastructure**
Installs Docker, Kubernetes, ingress-nginx, cert-manager, and storage.

```bash
./install-core-infrastructure.sh
```

**What it does:**
- Installs Docker with containerd
- Initializes Kubernetes 1.28 cluster
- Deploys Flannel networking
- Installs ingress-nginx with hostNetwork
- Installs cert-manager with Cloudflare DNS
- Creates storage infrastructure

**Configuration saved to:** `/root/.june-config/infrastructure.env`

---

### **Step 2: Networking (MetalLB + STUNner)**
Installs MetalLB LoadBalancer and STUNner TURN server with Gateway API v1alpha2.

```bash
./install-networking.sh
```

**What it does:**
- Installs MetalLB with your external IP
- Installs Gateway API v0.8.0 (with v1alpha2)
- Installs STUNner operator via Helm
- Creates STUNner Gateway with LoadBalancer
- Configures TURN authentication
- Creates ReferenceGrant for cross-namespace routing
- Generates ICE servers JSON configuration

**Configuration saved to:**
- `/root/.june-config/networking.env`
- `/root/.june-config/ice-servers.json`

**Verify:**
```bash
kubectl get gateway -n stunner
kubectl get svc -n stunner
python3 scripts/test-turn-server.py
```

---

### **Step 3: GPU Operator (Optional)**
Installs NVIDIA GPU Operator with time-slicing for multiple workloads.

```bash
./install-gpu-operator.sh
```

**What it does:**
- Installs NVIDIA GPU Operator via Helm
- Configures GPU time-slicing (2-8 virtual GPUs)
- Labels nodes with `gpu=true`

**Verify:**
```bash
kubectl get nodes -o json | jq '.items[].status.allocatable."nvidia.com/gpu"'
kubectl run gpu-test --rm -i --image=nvidia/cuda:11.0-base --restart=Never -- nvidia-smi
```

---

### **Step 4: GitHub Actions Runner (Optional)**
Sets up self-hosted GitHub Actions runner with Kubernetes access.

```bash
./install-github-runner.sh
```

**What it does:**
- Installs GitHub Actions runner software
- Configures as systemd service
- Sets up KUBECONFIG access
- Registers with your GitHub repository

**Verify:**
```bash
cd /opt/actions-runner && sudo ./svc.sh status
# Check: https://github.com/YOUR_REPO/settings/actions/runners
```

---

## 🌐 Domain Configuration

After installation, configure your DNS records:

```bash
# Get your external IP
curl http://checkip.amazonaws.com

# Add DNS A records (in Cloudflare or your DNS provider):
ozzu.world           A    YOUR_EXTERNAL_IP
*.ozzu.world         A    YOUR_EXTERNAL_IP
```

---

## 📦 Deploy June Services

After infrastructure is ready:

### **1. Apply STUNner UDPRoutes**

```bash
# Configure STUNner manifests with your credentials
kubectl apply -f /root/.june-config/stunner-manifests-configured.yaml
```

### **2. Deploy June Services**

```bash
# Apply main service manifests
kubectl apply -f k8s/complete-manifests.yaml

# Monitor deployment
kubectl get pods -n june-services -w
```

### **3. Verify Services**

```bash
# Check all services
kubectl get all -n june-services

# Test API endpoint
curl -k https://api.ozzu.world/healthz

# Test IDP
curl -k https://idp.ozzu.world

# Test TURN server
python3 scripts/test-turn-server.py
```

---

## 🔍 Configuration Files

All configuration is saved in `/root/.june-config/`:

| File | Description |
|------|-------------|
| `infrastructure.env` | Core infrastructure settings (CIDR, email, tokens) |
| `networking.env` | MetalLB and STUNner configuration |
| `domain-config.env` | Domain names and certificate configuration |
| `secrets.env` | Application secrets (Gemini API key) |
| `ice-servers.json` | WebRTC ICE servers configuration |
| `complete-manifests-configured.yaml` | Ready-to-deploy K8s manifests |
| `stunner-manifests-configured.yaml` | STUNner UDPRoutes with credentials |

---

## 🛠️ Command Line Options

The main orchestrator supports skipping components:

```bash
# Skip core infrastructure (if already installed)
./install-june-platform.sh --skip-core

# Skip networking (if already installed)
./install-june-platform.sh --skip-networking

# Skip GPU operator
./install-june-platform.sh --skip-gpu

# Skip GitHub runner
./install-june-platform.sh --skip-github

# Combine options
./install-june-platform.sh --skip-core --skip-gpu
```

---

## 🔧 Troubleshooting

### **MetalLB LoadBalancer Stuck on `<pending>`**

```bash
# Check MetalLB controller logs
kubectl logs -n metallb-system -l app=metallb

# Verify IP pool configuration
kubectl get ipaddresspool -n metallb-system

# Check if IP is assigned
kubectl get svc -n stunner -o wide
```

**Fix:**
```bash
# Reapply IP pool with correct external IP
kubectl apply -f - <<EOF
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: june-pool
  namespace: metallb-system
spec:
  addresses:
  - YOUR_EXTERNAL_IP/32
EOF
```

---

### **STUNner Gateway Not Ready**

```bash
# Check Gateway status
kubectl get gateway -n stunner -o yaml

# Check operator logs
kubectl logs -n stunner-system -l app.kubernetes.io/name=stunner-gateway-operator

# Check dataplane pods
kubectl get pods -n stunner
```

**Common issues:**
1. **Gateway API CRDs not installed:** Ensure v0.8.0 is installed (has v1alpha2)
2. **MetalLB not ready:** Gateway needs LoadBalancer IP assignment
3. **Wrong API version:** Must use `gateway.networking.k8s.io/v1alpha2`

---

### **TURN Server UDP Test Fails**

```bash
# Test locally first
python3 scripts/test-turn-server.py

# Check if UDP port is open
ss -ulnp | grep 3478

# Check firewall
ufw status
ufw allow 3478/udp
ufw allow 3478/tcp
```

---

### **Certificate Not Issued**

```bash
# Check certificate status
kubectl get certificate -n june-services

# Check cert-manager logs
kubectl logs -n cert-manager -l app=cert-manager

# Describe certificate for errors
kubectl describe certificate -n june-services
```

**Common issues:**
1. **Cloudflare API token invalid:** Check token permissions
2. **DNS propagation delay:** Wait 5-10 minutes
3. **Rate limit:** Use staging issuer first (`letsencrypt-staging`)

---

### **GPU Time-Slicing Not Working**

```bash
# Check GPU allocatable
kubectl get nodes -o json | jq '.items[].status.allocatable."nvidia.com/gpu"'

# Check device plugin logs
kubectl logs -n gpu-operator -l app=nvidia-device-plugin-daemonset

# Verify ConfigMap
kubectl get cm -n gpu-operator time-slicing-config -o yaml

# Check ClusterPolicy
kubectl get clusterpolicy -n gpu-operator cluster-policy -o yaml
```

**Fix:**
```bash
# Restart device plugin
kubectl delete pods -n gpu-operator -l app=nvidia-device-plugin-daemonset

# Wait for restart
kubectl wait --for=condition=ready pod \
    -n gpu-operator \
    -l app=nvidia-device-plugin-daemonset \
    --timeout=300s
```

---

## 📊 Monitoring & Health Checks

### **Check All Components**

```bash
# Core infrastructure
kubectl get nodes
kubectl get pods -n kube-system
kubectl get pods -n ingress-nginx
kubectl get pods -n cert-manager

# Networking
kubectl get pods -n metallb-system
kubectl get gateway -n stunner
kubectl get svc -n stunner

# June services
kubectl get pods -n june-services
kubectl get svc -n june-services
kubectl get ingress -n june-services

# GPU (if installed)
kubectl get pods -n gpu-operator
```

### **Service Endpoints Health**

```bash
# API
curl -k https://api.ozzu.world/healthz

# IDP
curl -k https://idp.ozzu.world/health/ready

# STT
curl -k https://stt.ozzu.world/healthz

# TTS
curl -k https://tts.ozzu.world/healthz
```

### **STUNner Connectivity Test**

```bash
# Use provided test script
python3 scripts/test-turn-server.py

# Or use online tester
# Visit: https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/
# Add: stun:turn.ozzu.world:3478
# Add: turn:turn.ozzu.world:3478 (with username/password)
```

---

## 🔄 Updating Components

### **Update STUNner Configuration**

```bash
# Edit configuration
kubectl edit gatewayconfig stunner-gatewayconfig -n stunner-system

# Or apply new manifest
kubectl apply -f k8s/stunner-manifests.yaml

# Restart Gateway
kubectl delete gateway june-stunner-gateway -n stunner
kubectl apply -f k8s/stunner-manifests.yaml
```

### **Update June Services**

```bash
# Pull latest images
kubectl set image deployment/june-orchestrator \
    orchestrator=ozzuworld/june-orchestrator:latest \
    -n june-services

# Or redeploy
kubectl rollout restart deployment/june-orchestrator -n june-services
kubectl rollout restart deployment/june-stt -n june-services
kubectl rollout restart deployment/june-tts -n june-services
```

### **Update Secrets**

```bash
# Update Gemini API key
kubectl create secret generic june-secrets \
    --from-literal=gemini-api-key="NEW_KEY_HERE" \
    --namespace=june-services \
    --dry-run=client -o yaml | kubectl apply -f -

# Restart services to pick up new secret
kubectl rollout restart deployment/june-orchestrator -n june-services
```

---

## 🗑️ Clean Uninstall

### **Remove June Services Only**

```bash
kubectl delete namespace june-services
```

### **Remove STUNner**

```bash
# Delete Gateway resources
kubectl delete gateway june-stunner-gateway -n stunner
kubectl delete gatewayclass stunner-gatewayclass
kubectl delete gatewayconfig stunner-gatewayconfig -n stunner-system

# Uninstall operator
helm uninstall stunner-gateway-operator -n stunner-system

# Remove namespaces
kubectl delete namespace stunner
kubectl delete namespace stunner-system
```

### **Remove MetalLB**

```bash
kubectl delete namespace metallb-system
```

### **Remove GPU Operator**

```bash
helm uninstall gpu-operator -n gpu-operator
kubectl delete namespace gpu-operator
```

### **Complete Cluster Reset**

```bash
# WARNING: This removes EVERYTHING
kubeadm reset -f
rm -rf /etc/kubernetes
rm -rf /var/lib/etcd
rm -rf /root/.kube

# Remove configuration
rm -rf /root/.june-config
rm -rf /opt/june-*
```

---

## 📚 Architecture Overview

### **Network Flow**

```
Client (Mobile/Web)
    ↓
DNS (*.ozzu.world → External IP)
    ↓
ingress-nginx (hostNetwork on port 80/443)
    ↓
June Services (june-services namespace)
    ├─ june-orchestrator (WebSocket + WebRTC)
    ├─ june-idp (Keycloak)
    ├─ june-stt (Whisper GPU)
    └─ june-tts (XTTS GPU)

WebRTC Audio
    ↓
STUN/TURN (turn.ozzu.world:3478)
    ↓
STUNner Gateway (LoadBalancer via MetalLB)
    ↓
UDPRoute → june-orchestrator
```

### **Component Dependencies**

```
1. Docker + containerd
2. Kubernetes 1.28
3. Flannel (Pod networking)
4. ingress-nginx (Ingress)
5. cert-manager (TLS certificates)
6. MetalLB (LoadBalancer)
7. Gateway API v1alpha2 (CRDs)
8. STUNner Operator (TURN server)
9. June Services (Applications)
```

---

## 🔐 Security Considerations

### **Firewall Rules**

```bash
# Allow essential ports
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw allow 3478/tcp  # TURN TCP
ufw allow 3478/udp  # TURN UDP
ufw allow 6443/tcp  # Kubernetes API
ufw enable
```

### **Secrets Management**

- ✅ All secrets stored in `/root/.june-config/` with 600 permissions
- ✅ Kubernetes secrets encrypted at rest
- ✅ Never commit secrets to Git
- ✅ Use `.gitignore` for config directory

### **TLS Certificates**

- ✅ Let's Encrypt production certificates
- ✅ Wildcard cert for `*.ozzu.world`
- ✅ Auto-renewal via cert-manager
- ✅ Backup script available: `scripts/install-k8s/backup-wildcard-cert.sh`

---

## 📖 Additional Resources

### **Documentation**
- **June Platform:** Your repository docs
- **STUNner:** https://docs.l7mp.io
- **Gateway API:** https://gateway-api.sigs.k8s.io
- **Kubernetes:** https://kubernetes.io/docs/
- **MetalLB:** https://metallb.universe.tf

### **Support**
- Open issues on GitHub
- Check logs first: `kubectl logs <pod-name> -n <namespace>`
- Use `kubectl describe` for resource details

---

## ✅ Post-Installation Checklist

- [ ] All infrastructure scripts completed successfully
- [ ] DNS records pointing to external IP
- [ ] TLS certificates issued (check `kubectl get certificate -n june-services`)
- [ ] STUNner Gateway ready (check `kubectl get gateway -n stunner`)
- [ ] MetalLB assigned IP to STUNner service
- [ ] UDPRoutes created for June services
- [ ] June services deployed and running
- [ ] Health checks passing on all endpoints
- [ ] TURN server UDP test passes
- [ ] GitHub runner connected (if installed)
- [ ] Configuration backed up to `/root/.june-config/`

---

**Installation complete!** 🎉

Your June Platform is ready for AI voice conversations with WebRTC support.