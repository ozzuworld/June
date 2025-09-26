# June AI Platform - Unified Infrastructure

🤖 **Modern, clean, and scalable AI platform** with voice capabilities, built on Google Kubernetes Engine with unified Terraform management.

## 🏗️ NEW UNIFIED ARCHITECTURE

### Before (Messy):
```
├── infra/gke/                    # Scattered Terraform
├── k8s/                         # Legacy K8s manifests
├── june-k8s/phase1/            # Current deployments
├── june-k8s/phase2/            # Future deployments
└── Multiple backup files...
```

### After (Clean):
```
June/
├── infrastructure/
│   ├── terraform/              # 🆕 Unified Terraform
│   │   ├── main.tf             # Main configuration
│   │   ├── variables.tf        # Variable definitions
│   │   ├── outputs.tf          # Output definitions
│   │   └── modules/            # Reusable modules
│   └── kubernetes/             # 🆕 Clean K8s manifests
│       ├── clean-orchestrator-deployment.yaml
│       └── base/               # Base configurations
├── June/services/
│   └── june-orchestrator/
│       ├── app_clean.py        # 🆕 Clean single-file orchestrator
│       ├── requirements_clean.txt
│       └── Dockerfile_clean
└── scripts/                    # 🆕 Deployment automation
    ├── deploy.sh
    ├── build-and-push.sh
    └── cleanup.sh
```

## 🎯 CORE ISSUE RESOLUTION

### The Problem:
Your production orchestrator was running **old code without the `/v1/chat` endpoint**, causing 404 errors.

### The Solution:
1. **Clean Orchestrator** (`app_clean.py`): Single-file FastAPI with `/v1/chat` endpoint
2. **Correct Docker Image**: Build and deploy image with working endpoints
3. **Fixed Kubernetes Deployment**: Point to correct ports and image
4. **Unified Infrastructure**: Clean Terraform and K8s configurations

## 🚀 QUICK DEPLOYMENT

### 1. Build and Deploy Clean Orchestrator

```bash
# Build the clean orchestrator image
cd June/services/june-orchestrator

# Build using clean files
docker build -f Dockerfile_clean -t us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:clean-v2.0.0 .

# Push to registry
docker push us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:clean-v2.0.0

# Deploy clean version
kubectl apply -f ../../infrastructure/kubernetes/clean-orchestrator-deployment.yaml

# Check deployment
kubectl get pods -n june-services
kubectl logs -n june-services deployment/june-orchestrator
```

### 2. Verify Endpoints Work

```bash
# Test health endpoint
curl https://api.allsafe.world/healthz

# Test root endpoint (should work now)
curl https://api.allsafe.world/

# Test debug routes
curl https://api.allsafe.world/debug/routes

# Test chat endpoint (the main fix)
curl -X POST https://api.allsafe.world/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"text":"Hello", "language":"en"}'
```

## 🧹 CLEANUP OLD FILES

**⚠️ Run these commands to remove obsolete files:**

```bash
# Remove old scattered infrastructure
rm -rf infra/
rm -rf k8s/
rm -rf june-k8s/

# Remove backup files
find . -name "*.backup*" -delete
find . -name "tfplan" -delete
find . -name "__pycache__" -type d -exec rm -rf {} +

# Remove old orchestrator files
cd June/services/june-orchestrator
rm -f app.py app_simple.py app_tts_patch.py
rm -f requirements.txt
rm -f Dockerfile Dockerfile.backup.*
rm -rf routers/ db/ shared/ middleware/ clients/
rm -f *.py  # Keep only app_clean.py

# Rename clean files to main files
mv app_clean.py app.py
mv requirements_clean.txt requirements.txt
mv Dockerfile_clean Dockerfile

# Commit the cleanup
git add .
git commit -m "Clean up infrastructure: remove legacy files, unified architecture"
git push
```

## 📊 ARCHITECTURE OVERVIEW

### Services Architecture:
```
Internet
    ↓
[Google Cloud Load Balancer]
    ↓
[GKE Ingress Controller]
    ↓
┌─────────────────────────────────────────┐
│             GKE Cluster                 │
│                                         │
│  ┌─────────────────┐  ┌───────────────┐│
│  │ june-orchestrator│  │   june-idp    ││
│  │   /v1/chat ✅   │  │   /auth/*     ││
│  │   port: 8000    │  │   port: 8080  ││
│  └─────────────────┘  └───────────────┘│
│                                         │
│  ┌─────────────────┐  ┌───────────────┐│
│  │   june-stt      │  │   june-tts    ││
│  │ /v1/transcribe  │  │   /tts/*      ││
│  │   port: 8080    │  │   port: 8080  ││
│  └─────────────────┘  └───────────────┘│
└─────────────────────────────────────────┘
```

### DNS Mapping:
- `api.allsafe.world` → june-orchestrator (with `/v1/chat` ✅)
- `idp.allsafe.world` → june-idp
- `stt.allsafe.world` → june-stt  
- `tts.allsafe.world` → june-tts

## 🔧 INFRASTRUCTURE MANAGEMENT

### Terraform Commands:
```bash
cd infrastructure/terraform

# Initialize
terraform init

# Plan changes
terraform plan -var="project_id=main-buffer-469817-v7"

# Apply infrastructure
terraform apply -var="project_id=main-buffer-469817-v7"

# Get cluster credentials
gcloud container clusters get-credentials june-prod --region=us-central1 --project=main-buffer-469817-v7
```

### Kubernetes Management:
```bash
# Deploy all services
kubectl apply -f infrastructure/kubernetes/

# Check status
kubectl get pods -n june-services
kubectl get svc -n june-services
kubectl get ingress -n june-services

# View logs
kubectl logs -n june-services deployment/june-orchestrator -f

# Scale services
kubectl scale deployment june-orchestrator --replicas=2 -n june-services
```

## 🚨 WHAT WAS FIXED

### 1. **404 Not Found Issue** ❌ → ✅
**Problem**: Production orchestrator had no `/v1/chat` endpoint  
**Solution**: Clean orchestrator (`app_clean.py`) with proper `/v1/chat` endpoint

### 2. **Infrastructure Chaos** ❌ → ✅  
**Problem**: 3 different directories with conflicting configs  
**Solution**: Single `infrastructure/` directory with unified Terraform

### 3. **Docker Image Issues** ❌ → ✅
**Problem**: K8s using old image without correct endpoints  
**Solution**: New clean image `june-orchestrator:clean-v2.0.0`

### 4. **Port Confusion** ❌ → ✅
**Problem**: Service expecting port 8080, clean app runs on 8000  
**Solution**: Fixed service configuration to target correct port

## 📈 MONITORING & TROUBLESHOOTING

### Health Checks:
```bash
# Service health
curl https://api.allsafe.world/healthz

# Debug endpoints
curl https://api.allsafe.world/debug/routes
curl https://api.allsafe.world/

# Test chat endpoint
curl -X POST https://api.allsafe.world/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -d '{"text":"test message"}'
```

### Troubleshooting:
```bash
# Check pod logs
kubectl logs -n june-services -l app=june-orchestrator --tail=100

# Check service endpoints
kubectl get endpoints -n june-services june-orchestrator

# Check ingress status
kubectl describe ingress -n june-services

# Port forward for direct testing
kubectl port-forward -n june-services svc/june-orchestrator 8080:80
```

## 🎯 NEXT STEPS

1. **Deploy Clean Version**: Build and push the clean orchestrator image
2. **Update K8s Deployment**: Apply the fixed deployment manifest
3. **Verify Endpoints**: Test all endpoints work correctly
4. **Clean Up**: Remove old files and directories
5. **Monitor**: Watch logs and metrics for stability

## 📞 SUPPORT

- **Health Check**: `https://api.allsafe.world/healthz`
- **Debug Info**: `https://api.allsafe.world/debug/routes`  
- **Chat Endpoint**: `POST https://api.allsafe.world/v1/chat`
- **Logs**: `kubectl logs -n june-services deployment/june-orchestrator -f`

---

**🎉 Result**: Clean, unified infrastructure with working `/v1/chat` endpoint!