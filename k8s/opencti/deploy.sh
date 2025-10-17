#!/bin/bash
# k8s/opencti/deploy.sh

set -e

NS="opencti"
RELEASE="opencti"

echo "🚀 Deploying OpenCTI..."

# Add helm repo
helm repo add opencti https://devops-ia.github.io/helm-opencti
helm repo update

# Deploy
helm upgrade --install "$RELEASE" opencti/opencti \
  --namespace "$NS" \
  --create-namespace \
  -f values.yaml \
  --wait

echo "✅ OpenCTI deployed!"
echo "URL: https://opencti.ozzu.world"
```

**Total: ~100 lines instead of 1200 lines**

---

## 🔍 **Why Is It Over-Engineered?**

### **Root Cause Analysis:**

1. **Namespace Issue Not Addressed**: Instead of fixing the FQDN problem, multiple workarounds were created
2. **Multiple Config Files**: Trying to handle different scenarios instead of having one clear path
3. **Auto-Detection Logic**: Shouldn't need to detect - infrastructure should be deterministic
4. **Recovery Scripts**: Needed because the initial config was wrong
5. **Bootstrap Scripts**: Helm can handle secrets and initialization

### **Red Flags:**
- ❌ Script names like `quick-fix.sh` (shouldn't need fixes)
- ❌ Script names like `opensearch-reset.sh` (shouldn't corrupt in first place)
- ❌ 3 different values files (one should work)
- ❌ Auto-detection logic (infrastructure should be explicit)
- ❌ Interactive troubleshooting menus (deployment should be idempotent)

---

## 📋 **Recommended Refactoring**

### **Keep:**
- ✅ `values.yaml` (single, correct config)
- ✅ `deploy.sh` (simple deployment script)
- ✅ `README.md` (minimal docs)

### **Remove:**
- ❌ `values-production.yaml` (you have OpenSearch already)
- ❌ `values-fixed.yaml` (wrong namespace)
- ❌ `install-opencti.sh` (too complex)
- ❌ `quick-fix.sh` (shouldn't be needed)
- ❌ `opensearch-reset.sh` (shouldn't corrupt)
- ❌ `bootstrap-admin.sh` (Helm handles this)

---

## 💡 **The Problem with Over-Engineering**

1. **Maintenance Burden**: 1200 lines to maintain vs 100 lines
2. **Cognitive Load**: New team members need to understand complex scripts
3. **Debugging Difficulty**: Multiple failure points
4. **False Confidence**: Scripts mask the real problem instead of fixing it

---

## 🎯 **My Recommendation**

**Delete everything in `k8s/opencti/` and replace with:**
```
k8s/opencti/
├── values.yaml          # Single config file (~80 lines)
├── deploy.sh            # Simple deployment (~20 lines)
└── README.md            # Basic usage (~30 lines)