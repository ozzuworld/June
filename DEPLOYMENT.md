# June Services Deployment Guide

This guide ensures clean deployments without duplicate replicas or conflicting configurations.

## 🚨 Important: Avoid Duplicate Replicas

The previous deployment issues were caused by:
1. **Namespace mismatch**: Stage2 script created `june` namespace, but services use `june-services`
2. **Image reference inconsistency**: Different files used `ozzuworld/image` vs `docker.io/ozzuworld/image`
3. **Multiple deployment sources**: Both stage2 and GitHub manifests created services

## 🚀 Recommended Deployment Process

### Step 1: Infrastructure Setup (Run Once)

```bash
# Use the FIXED version of stage2 script
chmod +x "scripts/k8s Install/stage2-install-k8s-ubuntu-fixed.sh"
sudo "./scripts/k8s Install/stage2-install-k8s-ubuntu-fixed.sh"
```

**What this does:**
- ✅ Sets up Kubernetes cluster
- ✅ Installs GPU Operator (if requested)
- ✅ Creates `june-services` namespace (FIXED)
- ✅ Sets up secrets in correct namespace
- ✅ Installs ingress controller
- ✅ **Does NOT deploy services** (prevents conflicts)

### Step 2: Deploy Services (Clean Method)

```bash
# Use the deployment script for clean deployment
chmod +x deploy-services.sh
./deploy-services.sh
```

**Or manually:**

```bash
# Option A: Use fixed complete manifests (recommended)
kubectl apply -f k8s/complete-manifests-fixed.yaml

# Option B: Use individual files (ensure consistency)
kubectl apply -f k8s/postgresql-deployment.yaml
kubectl apply -f k8s/june-stt-deployment.yaml
kubectl apply -f k8s/june-tts-deployment.yaml
kubectl apply -f k8s/june-orchestrator-deployment.yaml
kubectl apply -f k8s/june-idp-deployment.yaml
kubectl apply -f k8s/ingress.yaml
```

### Step 3: Verify No Duplicates

```bash
# Check deployments (should show 1 replica each)
kubectl get deployments -n june-services

# Check for duplicate ReplicaSets
kubectl get replicasets -n june-services

# Monitor pods
kubectl get pods -n june-services -w
```

## 🔧 Fixed Files Overview

### New Files Added:
- `scripts/k8s Install/stage2-install-k8s-ubuntu-fixed.sh` - Infrastructure only, correct namespace
- `deploy-services.sh` - Clean deployment script
- `k8s/complete-manifests-fixed.yaml` - Consistent `docker.io/` image references
- `DEPLOYMENT.md` - This guide

### Key Fixes:
1. **Consistent image references**: All use `docker.io/ozzuworld/service:latest`
2. **Correct namespace**: Everything uses `june-services`
3. **Separation of concerns**: Infrastructure setup vs service deployment
4. **Replica validation**: Scripts check for duplicates

## 🚨 Troubleshooting Duplicates

If you still see duplicate replicas:

```bash
# Clean up all deployments
kubectl delete deployment --all -n june-services

# Wait for pods to terminate
kubectl wait --for=delete pods --all -n june-services --timeout=60s

# Redeploy using clean method
./deploy-services.sh
```

## 🔍 Verification Commands

```bash
# Check cluster status
kubectl cluster-info

# Check namespace
kubectl get namespaces | grep june

# Check secrets
kubectl get secrets -n june-services

# Check all resources
kubectl get all -n june-services

# Check for image pull issues
kubectl describe pods -n june-services

# View logs
kubectl logs -l app=june-stt -n june-services
```

## 🎨 Best Practices

1. **Always use the fixed scripts** for new deployments
2. **Choose ONE deployment method** (complete-manifests-fixed.yaml recommended)
3. **Verify image references** are consistent across all files
4. **Check for duplicates** after deployment
5. **Clean up** old deployments before redeploying

## 🔄 Migration from Old Setup

If you have an existing deployment with duplicates:

```bash
# 1. Clean up existing deployment
kubectl delete namespace june-services

# 2. Run fixed infrastructure setup
sudo "./scripts/k8s Install/stage2-install-k8s-ubuntu-fixed.sh"

# 3. Deploy services cleanly
./deploy-services.sh
```

This ensures a completely fresh start with the corrected configuration.
