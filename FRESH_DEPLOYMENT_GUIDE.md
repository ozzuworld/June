# June Platform - Fresh Deployment Guide

## 🚀 Complete Fresh Deployment Instructions

This guide ensures your June platform will work correctly from a fresh installation, including all the latest LiveKit integration fixes.

## ✅ Pre-Deployment Validation

**ALWAYS run this validation script before deploying:**

```bash
git clone https://github.com/ozzuworld/June.git
cd June
chmod +x scripts/validate-fresh-deployment.sh
./scripts/validate-fresh-deployment.sh
```

This script checks:
- ✅ LiveKit SDK version compatibility (0.8.0)
- ✅ Ingress configuration for cross-namespace routing
- ✅ ConfigMap LiveKit URLs
- ✅ Environment variable mapping
- ✅ Helm chart structure

## 🔧 Prerequisites

### 1. Server Requirements
- **OS**: Ubuntu 20.04+ or similar Linux distribution
- **RAM**: Minimum 8GB (16GB+ recommended)
- **CPU**: 4+ cores
- **Storage**: 50GB+ available space
- **Network**: Public IP with ports 80, 443, 3478 accessible

### 2. DNS Configuration

**Before installation**, configure these DNS records:

```
your-domain.com         A    YOUR_SERVER_IP
*.your-domain.com       A    YOUR_SERVER_IP
```

**Critical**: The wildcard record is required for `livekit.your-domain.com`

### 3. API Keys Required

- **Cloudflare API Token** (for SSL certificates)
- **Google Gemini API Key** (for AI features)

## 🏗️ Installation Steps

### Step 1: Clone and Configure

```bash
# Clone the repository
git clone https://github.com/ozzuworld/June.git
cd June

# Make scripts executable
chmod +x install.sh
chmod +x scripts/*.sh

# Create configuration
cp config.env.example config.env
nano config.env
```

### Step 2: Update Configuration

Edit `config.env`:

```bash
# Domain Configuration
DOMAIN="your-domain.com"
LETSENCRYPT_EMAIL="admin@your-domain.com"

# API Keys (REQUIRED)
GEMINI_API_KEY="your-gemini-api-key"
CLOUDFLARE_TOKEN="your-cloudflare-token"

# Optional: Customize passwords
POSTGRESQL_PASSWORD="secure-password"
KEYCLOAK_ADMIN_PASSWORD="admin-password"
STUNNER_PASSWORD="turn-password"
```

### Step 3: Run Validation (Critical)

```bash
./scripts/validate-fresh-deployment.sh
```

**Do not proceed if validation fails!**

### Step 4: Install

```bash
sudo ./install.sh
```

Installation takes 15-30 minutes and includes:
- ✅ Kubernetes cluster setup
- ✅ nginx-ingress + cert-manager
- ✅ STUNner (TURN server)
- ✅ LiveKit (WebRTC server)
- ✅ June Platform services
- ✅ SSL certificates

## 🎯 Post-Installation Verification

### 1. Check Service Status

```bash
# Core services
kubectl get pods -n june-services

# LiveKit
kubectl get pods -n media

# STUNner
kubectl get pods -n stunner
```

### 2. Test Endpoints

```bash
# Orchestrator API (should return session with token)
curl -i https://api.your-domain.com/api/sessions/ \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"test","room_name":"test-room"}'

# LiveKit (should return "OK")
curl -i https://livekit.your-domain.com/

# Identity Provider
curl -i https://idp.your-domain.com/
```

### 3. Expected Results

**Orchestrator API Response:**
```json
{
  "session_id": "uuid",
  "user_id": "test",
  "room_name": "test-room",
  "access_token": "jwt-token",
  "livekit_url": "wss://livekit.your-domain.com",
  "created_at": "2025-10-14T...",
  "status": "active"
}
```

**LiveKit Response:**
```
HTTP/2 200 OK
...
OK
```

## 🔧 Architecture Overview

### Service Endpoints
- **API**: `https://api.your-domain.com` (Orchestrator)
- **LiveKit**: `https://livekit.your-domain.com` (WebRTC)
- **Identity**: `https://idp.your-domain.com` (Keycloak)
- **STT**: `https://stt.your-domain.com` (if GPU available)
- **TTS**: `https://tts.your-domain.com` (if GPU available)

### Key Components
- **june-services** namespace: Core application services
- **media** namespace: LiveKit WebRTC server
- **stunner** namespace: TURN server for NAT traversal
- **cert-manager** namespace: SSL certificate management

### Cross-Namespace Communication
- **livekit-proxy** service: Routes `june-services` → `media` namespace
- **ExternalName** service type for cross-namespace access
- **ReferenceGrant** for STUNner → LiveKit communication

## 🚨 Common Issues & Solutions

### Issue: LiveKit returns 503 Service Unavailable

**Cause**: Cross-namespace routing not working

**Solution**:
```bash
# Check proxy service
kubectl get service livekit-proxy -n june-services

# Recreate if missing
kubectl delete service livekit-proxy -n june-services --ignore-not-found
./scripts/fix-livekit-quick.sh
```

### Issue: Orchestrator returns VideoGrant error

**Cause**: Old LiveKit SDK version

**Solution**:
```bash
# Check requirements
grep livekit June/services/june-orchestrator/requirements.txt

# Should show:
# livekit-api==0.8.0
# livekit-protocol==0.8.0

# Rebuild if needed
kubectl rollout restart deployment/june-orchestrator -n june-services
```

### Issue: SSL certificate not working

**Cause**: DNS not properly configured or Cloudflare token issues

**Solution**:
```bash
# Check certificate status
kubectl get certificates -n june-services

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager

# Verify DNS propagation
nslookup livekit.your-domain.com
```

## 🔄 Updates & Maintenance

### Update June Platform

```bash
cd June
git pull origin master

# Validate changes
./scripts/validate-fresh-deployment.sh

# Apply updates
helm upgrade june-platform ./helm/june-platform \
  --namespace june-services \
  --reuse-values
```

### Monitor Services

```bash
# Watch all pods
kubectl get pods --all-namespaces -w

# Check logs
kubectl logs -n june-services -l app=june-orchestrator
kubectl logs -n media -l app.kubernetes.io/name=livekit-server
```

## 🎉 Success!

If all tests pass, your June platform is ready for:
- 🎤 Voice processing with OpenVoice v2
- 📹 Real-time WebRTC communication via LiveKit
- 🤖 AI-powered conversation orchestration
- 🔐 Secure authentication with Keycloak
- 🌐 Production-ready SSL endpoints

---

**Need help?** Check the validation script output or review the troubleshooting section above.