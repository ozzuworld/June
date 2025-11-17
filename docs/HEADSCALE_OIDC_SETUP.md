# Headscale OIDC Authentication with Keycloak

This guide explains how to set up OpenID Connect (OIDC) authentication for Headscale VPN using Keycloak as the identity provider. This enables seamless SSO login where users authenticate with their Keycloak credentials to automatically connect to the VPN.

## Overview

The integration provides a streamlined authentication flow:

```
User opens VPN app/client
    ↓
Runs: tailscale up --login-server=https://headscale.ozzu.world
    ↓
Browser opens with Keycloak login page
    ↓
User enters Keycloak credentials
    ↓
Keycloak authenticates and redirects back to Headscale
    ↓
Headscale auto-registers the device
    ↓
VPN connected! ✅
```

## Architecture

- **Headscale**: Self-hosted Tailscale control server running in Kubernetes (`headscale` namespace)
- **Keycloak**: Identity provider running as `june-idp` in `june-services` namespace
- **OIDC Protocol**: Standard OpenID Connect with PKCE for enhanced security
- **Authentication**: Users authenticate against Keycloak realm `allsafe`

## Prerequisites

Before setting up OIDC authentication, ensure:

1. Headscale is installed and running:
   ```bash
   ./scripts/install/04.6-headscale.sh
   ```

2. Keycloak is installed, running, and provisioned:
   ```bash
   # Keycloak should already be running as part of June platform
   kubectl get pods -n june-services -l app=june-idp
   ```

3. You have access to Keycloak admin console:
   ```
   URL: https://idp.ozzu.world
   Username: admin
   Password: [from config.env]
   ```

## Installation Steps

### Step 1: Configure Keycloak OIDC Client

Run the OIDC provisioning script:

```bash
cd /home/user/June
./scripts/install/04.6.1-headscale-oidc.sh
```

This script will:
- Create a Keycloak OIDC client named `headscale-vpn`
- Configure the redirect URI: `https://headscale.ozzu.world/oidc/callback`
- Enable PKCE (S256) for enhanced security
- Set up required protocol mappers for email and email_verified claims
- Generate a client secret
- Create a Kubernetes secret `headscale-oidc` in the `headscale` namespace

### Step 2: Update Headscale Configuration

Re-run the Headscale installation script to apply OIDC configuration:

```bash
./scripts/install/04.6-headscale.sh
```

The script will:
- Detect the `headscale-oidc` Kubernetes secret
- Update the ConfigMap with OIDC settings
- Restart the Headscale deployment to apply changes

### Step 3: Verify Configuration

Check that Headscale is running with OIDC enabled:

```bash
# Check pod status
kubectl get pods -n headscale

# Check logs for OIDC initialization
kubectl logs -n headscale deployment/headscale | grep -i oidc

# Verify ConfigMap contains OIDC section
kubectl get configmap headscale-config -n headscale -o yaml | grep -A 10 oidc
```

Expected log output:
```
INFO OIDC configuration loaded
INFO OIDC issuer: https://idp.ozzu.world/realms/allsafe
```

## Client Connection

### First-Time Connection

On any client device (laptop, phone, tablet):

1. **Install Tailscale client**:
   - Linux: `curl -fsSL https://tailscale.com/install.sh | sh`
   - macOS: `brew install tailscale`
   - iOS/Android: Download from App Store/Play Store

2. **Connect with OIDC**:
   ```bash
   tailscale up --login-server=https://headscale.ozzu.world
   ```

3. **Browser Authentication**:
   - Browser automatically opens to Keycloak login page
   - Enter your Keycloak credentials
   - Approve any consent screens
   - Browser shows "Success! You can close this window"

4. **Verification**:
   ```bash
   # Check VPN status
   tailscale status

   # Get your VPN IP
   tailscale ip -4
   ```

### Mobile App Flow (The Frontend Team Request)

For the mobile app integration where users should seamlessly connect:

**User Journey**:
```
1. User opens mobile app
2. Taps "Login" → App navigates to Keycloak
3. User enters credentials → Keycloak authenticates
4. App receives auth token
5. User taps "Connect VPN" → App calls Tailscale SDK
6. SDK uses OIDC flow with headscale.ozzu.world
7. VPN connected automatically!
```

**Mobile Implementation Example** (React Native):

```javascript
import Tailscale from '@tailscale/react-native';

// After user logs in with Keycloak
const connectToVPN = async () => {
  try {
    // Configure Tailscale with custom control server
    await Tailscale.configure({
      controlURL: 'https://headscale.ozzu.world'
    });

    // Start VPN - will use OIDC authentication
    // Browser/webview opens for Keycloak login
    await Tailscale.up();

    console.log('VPN Connected!');
  } catch (error) {
    console.error('VPN connection failed:', error);
  }
};
```

## User Management

### OIDC Users

When users authenticate via OIDC, Headscale automatically creates user accounts based on their email:

```bash
# List all users (includes OIDC users)
kubectl exec -n headscale deployment/headscale -- headscale users list

# Example output:
# ID | Name                    | Created
# 1  | user@ozzu.world        | 2025-11-17
# 2  | admin@ozzu.world       | 2025-11-17
```

### Managing Nodes

```bash
# List all connected nodes
kubectl exec -n headscale deployment/headscale -- headscale nodes list

# Expire a specific node (force re-authentication)
kubectl exec -n headscale deployment/headscale -- headscale nodes expire <node-id>

# Delete a node
kubectl exec -n headscale deployment/headscale -- headscale nodes delete <node-id>
```

## Advanced Configuration

### Restrict Access by Email Domain

To only allow users from specific domains:

Edit the Headscale ConfigMap:
```yaml
oidc:
  issuer: "https://idp.ozzu.world/realms/allsafe"
  client_id: "headscale-vpn"
  client_secret: "..."
  scope: ["openid", "profile", "email"]
  allowed_domains: ["ozzu.world"]  # Only allow @ozzu.world emails
```

### Restrict Access by Email

To whitelist specific users:

```yaml
oidc:
  issuer: "https://idp.ozzu.world/realms/allsafe"
  client_id: "headscale-vpn"
  client_secret: "..."
  scope: ["openid", "profile", "email"]
  allowed_users:
    - "admin@ozzu.world"
    - "developer@ozzu.world"
```

### Custom Token Expiration

Match VPN session to Keycloak token expiration:

```yaml
oidc:
  issuer: "https://idp.ozzu.world/realms/allsafe"
  client_id: "headscale-vpn"
  client_secret: "..."
  scope: ["openid", "profile", "email"]
  use_expiry_from_token: true  # Use Keycloak token expiration
  # OR set fixed expiration
  expiry: 30d  # 30 days
```

## Troubleshooting

### "OIDC provider is not available"

**Cause**: Headscale can't reach Keycloak

**Solution**:
```bash
# Check Keycloak is running
kubectl get pods -n june-services -l app=june-idp

# Test OIDC discovery endpoint
curl -k https://idp.ozzu.world/realms/allsafe/.well-known/openid-configuration

# Check Headscale logs
kubectl logs -n headscale deployment/headscale
```

### "Invalid client or client secret"

**Cause**: OIDC credentials mismatch

**Solution**:
```bash
# Re-run OIDC provisioning
./scripts/install/04.6.1-headscale-oidc.sh

# Verify secret exists
kubectl get secret headscale-oidc -n headscale -o yaml

# Restart Headscale
kubectl rollout restart deployment/headscale -n headscale
```

### "Email not verified" error

**Cause**: Keycloak user email not verified

**Solution**:
1. Log into Keycloak admin console
2. Navigate to: Users → [select user]
3. Check "Email Verified" checkbox
4. Save

Or verify via API:
```bash
# In Keycloak provisioning, ensure email_verified mapper is present
```

### Browser doesn't open on mobile

**Cause**: Mobile app needs to handle OAuth flow

**Solution**:
- Use in-app browser or system browser
- Implement proper OAuth redirect handling
- Use Tailscale mobile SDK with custom control server

### Connection works but can't access resources

**Cause**: ACL (Access Control List) restrictions

**Solution**:
```bash
# Check current ACL policy
kubectl exec -n headscale deployment/headscale -- headscale policy get

# Update ACL to allow all traffic (testing)
kubectl exec -n headscale deployment/headscale -- headscale policy set - <<EOF
{
  "acls": [
    {
      "action": "accept",
      "src": ["*"],
      "dst": ["*:*"]
    }
  ]
}
EOF
```

## Security Considerations

1. **PKCE Enabled**: All OIDC flows use PKCE (S256) to prevent authorization code interception

2. **HTTPS Only**: All communication is over HTTPS with valid certificates

3. **Token Expiration**: Tokens expire after 24 hours by default (configurable in Keycloak)

4. **Client Secret Protection**: Secrets stored in Kubernetes secrets, not in ConfigMaps

5. **Domain Restrictions**: Optionally restrict to specific email domains

6. **Email Verification**: Requires `email_verified: true` from Keycloak

## Keycloak Client Configuration

For reference, the OIDC client in Keycloak has these settings:

- **Client ID**: `headscale-vpn`
- **Client Protocol**: openid-connect
- **Access Type**: confidential
- **Standard Flow**: Enabled
- **Direct Access Grants**: Disabled
- **Service Accounts**: Disabled
- **Valid Redirect URIs**: `https://headscale.ozzu.world/oidc/callback`
- **Web Origins**: `https://headscale.ozzu.world`
- **PKCE Code Challenge Method**: S256

**Protocol Mappers**:
- `email`: Maps user email to `email` claim
- `email_verified`: Maps email verification status to `email_verified` claim

## Maintenance

### Rotating Client Secret

```bash
# 1. Generate new secret in Keycloak
# (via Admin UI or script)

# 2. Update Kubernetes secret
kubectl create secret generic headscale-oidc \
  -n headscale \
  --from-literal=client-id="headscale-vpn" \
  --from-literal=client-secret="NEW_SECRET_HERE" \
  --from-literal=issuer="https://idp.ozzu.world/realms/allsafe" \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Re-run configuration script
./scripts/install/04.6-headscale.sh
```

### Monitoring

```bash
# Watch Headscale logs
kubectl logs -n headscale deployment/headscale -f

# Check authentication events
kubectl logs -n headscale deployment/headscale | grep "OIDC\|authentication"

# Monitor connected nodes
watch kubectl exec -n headscale deployment/headscale -- headscale nodes list
```

## Additional Resources

- [Headscale OIDC Documentation](https://headscale.net/stable/ref/oidc/)
- [Keycloak OIDC Documentation](https://www.keycloak.org/docs/latest/server_admin/#_oidc)
- [Tailscale Custom OIDC Guide](https://tailscale.com/kb/1240/sso-custom-oidc)

## Support

For issues or questions:

1. Check Headscale logs: `kubectl logs -n headscale deployment/headscale`
2. Check Keycloak logs: `kubectl logs -n june-services deployment/june-idp`
3. Verify network connectivity between services
4. Review this documentation for troubleshooting steps
