# Deployment Next Steps: VPN Registration with kubectl Support

## Summary

I've implemented the seamless VPN registration feature with Headscale pre-authentication keys. All code changes are complete and pushed to the branch `claude/add-headscale-support-013pGdDwcUk1R1spKasgpDRJ`.

**What's been completed:**
- ✅ Added kubectl to orchestrator Dockerfile
- ✅ Created RBAC permissions for pod exec (ServiceAccount, Role, RoleBinding)
- ✅ Updated Helm chart with ServiceAccount and environment variables
- ✅ Fixed GitHub Actions workflow for correct build context
- ✅ All changes committed and pushed

**What needs to be done manually:**
- 🔨 Build and deploy the new Docker image
- 🧪 Test the seamless VPN registration endpoint

## Option 1: Build with GitHub Actions (Recommended)

Trigger the GitHub Actions workflow to build the orchestrator image:

1. Go to: https://github.com/ozzuworld/June/actions/workflows/build-june-services.yml

2. Click "Run workflow" and select:
   - **Branch**: `claude/add-headscale-support-013pGdDwcUk1R1spKasgpDRJ`
   - **Service**: `june-orchestrator`
   - **Image tag**: `latest` (or use a specific tag like `v3.0.0-kubectl`)
   - **Registry**: `ghcr.io` (default) or `docker.io`
   - **Push to registry**: `true`

3. Wait for the build to complete

4. If using `ghcr.io`, update Helm values:
   ```bash
   # Update helm/june-platform/values.yaml
   # Change orchestrator.image.repository to:
   # repository: ghcr.io/ozzuworld/june-orchestrator
   ```

5. Deploy with Helm:
   ```bash
   cd /home/user/June
   helm upgrade june-platform ./helm/june-platform \
     --namespace june-services \
     --values ./helm/june-platform/values.yaml
   ```

## Option 2: Build Locally

If you have Docker available locally:

```bash
cd /home/user/June

# Build the image
./scripts/build-orchestrator.sh

# This will:
# 1. Build the Docker image with kubectl
# 2. Push to docker.io/ozzuworld/june-orchestrator:latest
# 3. Restart the Kubernetes deployment
# 4. Test the endpoint
```

## Verification Steps

After deployment, verify kubectl is available:

```bash
# Get the orchestrator pod name
POD=$(kubectl get pod -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}')

# Check if kubectl is installed
kubectl exec -n june-services $POD -- kubectl version --client

# Expected output: Client Version information
```

## Test the VPN Registration Endpoint

Once deployed, test the endpoint:

```bash
# Get a Keycloak access token first
TOKEN="<your-keycloak-access-token>"

# Test device registration
curl -X POST https://api.ozzu.world/api/v1/device/register \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "device_os": "ios",
    "device_model": "iPhone 15 Pro"
  }' | jq

# Expected response:
# {
#   "success": true,
#   "message": "Device registration ready. Use the pre-auth key to connect.",
#   "device_name": "username-ios-<timestamp>",
#   "login_server": "https://headscale.ozzu.world",
#   "pre_auth_key": "<generated-key>",
#   "expiration": "24h",
#   "instructions": { ... }
# }
```

## Key Changes Made

### 1. Dockerfile (`June/services/june-orchestrator/Dockerfile`)
```dockerfile
# Install kubectl for Headscale CLI access
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl \
    && rm -rf /var/lib/apt/lists/*
```

### 2. RBAC Permissions
Created `k8s/rbac/orchestrator-headscale-access.yaml` and embedded in Helm template:
- ServiceAccount: `june-orchestrator`
- Role: `headscale-exec` (in headscale namespace)
- RoleBinding: Grants orchestrator SA access to exec into Headscale pods

### 3. VPN Registration Flow
```
User → [Keycloak Auth] → Get Bearer Token
     ↓
Frontend → POST /api/v1/device/register (with Bearer token)
     ↓
Backend → Validate token
       → Create Headscale user (kubectl exec)
       → Generate pre-auth key (kubectl exec)
       → Return pre-auth key
     ↓
Frontend → Use Tailscale SDK with pre-auth key
        → VPN connects automatically (NO BROWSER NEEDED!)
```

## Troubleshooting

### If kubectl is missing after deployment:
```bash
# Check if image was rebuilt
kubectl describe pod -n june-services -l app=june-orchestrator | grep Image:

# Should show the new image with recent timestamp
```

### If RBAC permissions are missing:
```bash
# Verify ServiceAccount exists
kubectl get sa june-orchestrator -n june-services

# Verify Role exists
kubectl get role headscale-exec -n headscale

# Verify RoleBinding exists
kubectl get rolebinding june-orchestrator-headscale-exec -n headscale
```

### If endpoint still returns 500:
```bash
# Check orchestrator logs
kubectl logs -n june-services -l app=june-orchestrator --tail=100
```

## Files Modified

- `June/services/june-orchestrator/Dockerfile` - Added kubectl
- `June/services/june-orchestrator/app/routes/vpn.py` - VPN registration API
- `June/services/shared/auth.py` - JWT validation fixes
- `helm/june-platform/templates/june-orchestrator.yaml` - Added RBAC and env vars
- `k8s/rbac/orchestrator-headscale-access.yaml` - RBAC configuration
- `.github/workflows/build-june-services.yml` - Fixed build context
- `June/services/june-orchestrator/requirements.txt` - Added PyJWT, cryptography

## Next Steps

1. **Build the image** using Option 1 (GitHub Actions) or Option 2 (local build)
2. **Deploy** with Helm if using GitHub Actions
3. **Verify** kubectl is available in the pod
4. **Test** the VPN registration endpoint
5. **Integrate** with frontend using the pre-auth key flow

The seamless VPN registration is ready once the image is rebuilt and deployed!
