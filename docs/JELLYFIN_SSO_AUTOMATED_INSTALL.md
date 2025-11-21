# Jellyfin SSO - Fully Automated Installation

## Overview

Jellyfin SSO is now **100% automated** using infrastructure-as-code principles. No manual steps required.

## How It Works

### 1. Custom Docker Image
We build a custom Jellyfin Docker image with the SSO plugin **pre-installed**:

```dockerfile
FROM jellyfin/jellyfin:latest
# Download and install SSO-Auth plugin
RUN mkdir -p /config/data/plugins/SSO-Auth && \
    curl -L https://github.com/9p4/jellyfin-plugin-sso/releases/download/v4.0.0.3/sso-authentication_4.0.0.3.zip -o /tmp/sso-plugin.zip && \
    unzip /tmp/sso-plugin.zip -d /config/data/plugins/SSO-Auth/
```

### 2. Automated Deployment
The install script (`scripts/install/media-stack/01-jellyfin.sh`):
1. Builds the custom Docker image with SSO plugin
2. Deploys Jellyfin using the custom image via Helm
3. Plugin is available immediately on first boot

### 3. Automated Configuration
The SSO configuration script (`scripts/install/09.5-keycloak-media-sso.sh`):
1. Provisions Keycloak OIDC clients
2. Waits for Jellyfin to be ready
3. Configures the pre-installed SSO plugin via API
4. Adds SSO button to login page
5. Verifies SSO endpoint works

## Installation Flow

```
┌──────────────────────────────────────────────┐
│ 1. Build Custom Docker Image                │
│    docker/jellyfin-sso/Dockerfile           │
│    ✓ SSO plugin pre-installed               │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ 2. Deploy Jellyfin with Custom Image        │
│    scripts/install/media-stack/01-jellyfin  │
│    ✓ Helm deployment uses custom image      │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ 3. Provision Keycloak Clients               │
│    scripts/automation-media-stack/           │
│    provision-keycloak-media-sso.sh          │
│    ✓ Creates jellyfin & jellyseerr clients  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ 4. Configure SSO Plugin                     │
│    scripts/automation-media-stack/           │
│    configure-sso-only.py                    │
│    ✓ Configures plugin via Jellyfin API     │
│    ✓ Adds SSO button to login page         │
│    ✓ Verifies SSO endpoint                  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
                ✅ DONE
     SSO Ready to Use - No Manual Steps!
```

## Main Install Orchestrator

The main install script includes these phases:

```bash
PHASES=(
    ...
    "media-stack/01-jellyfin"         # Builds custom image + deploys
    "09.5-keycloak-media-sso"          # Configures SSO
    ...
)
```

When you run:
```bash
sudo ./scripts/install-orchestrator.sh
```

Everything is automated:
1. ✅ Custom Jellyfin image built
2. ✅ Jellyfin deployed with SSO plugin
3. ✅ Keycloak clients provisioned
4. ✅ SSO configured automatically
5. ✅ SSO button added to login page

## Files Involved

### Docker Image
- `docker/jellyfin-sso/Dockerfile` - Custom image with SSO plugin

### Build Scripts
- `scripts/install/media-stack/00.5-build-jellyfin-image.sh` - Builds custom image

### Deployment Scripts
- `scripts/install/media-stack/01-jellyfin.sh` - Deploys Jellyfin with custom image

### SSO Configuration
- `scripts/automation-media-stack/provision-keycloak-media-sso.sh` - Creates Keycloak clients
- `scripts/automation-media-stack/configure-sso-only.py` - Configures SSO plugin

### Installation Phases
- `scripts/install/09.5-keycloak-media-sso.sh` - Orchestrates SSO setup

## Testing

After installation:

```bash
# Check Jellyfin is using custom image
kubectl get pods -n media-stack -o jsonpath='{.items[0].spec.containers[0].image}'
# Should show: jellyfin-sso:latest

# Test SSO endpoint
curl -I https://tv.ozzu.world/sso/OID/start/keycloak
# Should redirect to Keycloak
```

## Frontend Integration

Once SSO is configured, frontend should:

**❌ Remove hardcoded credentials:**
```javascript
// DELETE THIS
const JELLYFIN_USERNAME = "hadmin";
const JELLYFIN_PASSWORD = "Pokemon123!";
```

**✅ Use SSO redirect:**
```javascript
function loginToJellyfin() {
  window.location.href = 'https://tv.ozzu.world/sso/OID/start/keycloak';
}
```

See: `docs/FRONTEND_JELLYFIN_SSO_INTEGRATION.md`

## Troubleshooting

### SSO Plugin Not Found

If the SSO plugin isn't working:

1. **Check if custom image was built:**
   ```bash
   docker images | grep jellyfin-sso
   ```

2. **Check Jellyfin pod is using custom image:**
   ```bash
   kubectl describe pod -n media-stack -l app.kubernetes.io/name=jellyfin | grep Image:
   ```

3. **Check plugin is installed in pod:**
   ```bash
   kubectl exec -n media-stack deployment/jellyfin -- ls -la /config/data/plugins/
   ```

### Rebuild Custom Image

If you need to rebuild the image:

```bash
cd /home/user/June
bash scripts/install/media-stack/00.5-build-jellyfin-image.sh
```

### Reconfigure SSO

If SSO configuration failed:

```bash
cd /home/user/June
source config.env

python3 scripts/automation-media-stack/configure-sso-only.py \
  --jellyfin-url "https://tv.${DOMAIN}" \
  --username "$JELLYFIN_USERNAME" \
  --password "$JELLYFIN_PASSWORD" \
  --keycloak-url "$KEYCLOAK_URL" \
  --realm "${KEYCLOAK_REALM:-allsafe}" \
  --client-secret "$(source /tmp/media-sso-config.env && echo $JELLYFIN_CLIENT_SECRET)" \
  --domain "$DOMAIN"
```

## Why This Approach?

### ❌ What Didn't Work
- Installing plugin via Jellyfin API (unreliable)
- Manual plugin installation (not infrastructure-as-code)
- Separate "fix" scripts (workarounds, not solutions)

### ✅ What Works
- Custom Docker image with plugin pre-installed
- Declarative infrastructure (Dockerfile + Helm)
- Single install script does everything
- Repeatable, version-controlled, automated

## Summary

**Before**: Manual plugin installation, separate fix scripts, unreliable API calls

**Now**:
- Custom Docker image with plugin baked in
- Fully automated installation
- Infrastructure-as-code
- No manual steps
- Works every time

```bash
# Just run the install script
sudo ./scripts/install-orchestrator.sh

# SSO works automatically ✅
```
