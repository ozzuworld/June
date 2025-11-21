# Jellyfin SSO Fix - Issue Summary and Resolution

## 🔴 Problem Report

**Issue**: Frontend team had to hardcode Jellyfin credentials because SSO was not working.

**Root Cause**: Jellyfin SSO plugin requires manual installation and configuration steps that were not automated or properly verified.

## 🔍 Technical Analysis

### What Was Broken

1. **Manual Plugin Installation Required**
   - The `jellyfin-plugin-sso` must be installed via Jellyfin dashboard
   - Cannot be installed programmatically without manual steps
   - Original setup script only provided instructions, didn't verify completion

2. **Missing Verification**
   - No automated way to check if SSO plugin was installed
   - No verification that SSO configuration was applied correctly
   - No testing of the SSO endpoint

3. **Frontend Integration Gap**
   - No documentation on how frontend should use SSO
   - Frontend developers resorted to hardcoding credentials as workaround
   - Security risk: credentials exposed in frontend code

### Configuration Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Keycloak (Identity Provider)                               │
│  - Realm: allsafe                                           │
│  - OIDC Client: jellyfin                                    │
│  - Roles: jellyfin-admin, jellyfin-user                     │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ OIDC Protocol
                  │
┌─────────────────▼───────────────────────────────────────────┐
│  Jellyfin (Media Server)                                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ SSO Plugin (jellyfin-plugin-sso)                     │  │
│  │ - Validates Keycloak tokens                          │  │
│  │ - Creates Jellyfin sessions                          │  │
│  │ - Maps roles from Keycloak                           │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ Jellyfin API
                  │
┌─────────────────▼───────────────────────────────────────────┐
│  Frontend (Web/Mobile App)                                  │
│  ❌ OLD: Hardcoded credentials                              │
│  ✅ NEW: Redirect to SSO URL                                │
└─────────────────────────────────────────────────────────────┘
```

## ✅ Solution Implemented

### 1. Automated Verification Script

Created `/scripts/automation-media-stack/verify-and-fix-jellyfin-sso.py`:

**Features**:
- ✅ Authenticates with Jellyfin
- ✅ Checks if SSO plugin is installed
- ✅ Verifies SSO configuration
- ✅ Auto-configures SSO if `--fix` flag provided
- ✅ Tests SSO endpoint functionality
- ✅ Provides actionable error messages

**Usage**:
```bash
python3 verify-and-fix-jellyfin-sso.py \
  --jellyfin-url "https://tv.ozzu.world" \
  --username "admin" \
  --password "password" \
  --keycloak-url "https://idp.ozzu.world" \
  --realm "allsafe" \
  --domain "ozzu.world" \
  --client-secret "xxx" \
  --fix
```

### 2. One-Command Fix Script

Created `/scripts/automation-media-stack/fix-jellyfin-sso-now.sh`:

**What it does**:
1. Loads configuration from `config.env`
2. Provisions Keycloak OIDC clients (if needed)
3. Runs verification and auto-fix
4. Provides clear instructions if manual steps required
5. Shows SSO URL for frontend integration

**Usage**:
```bash
cd /home/user/June
bash scripts/automation-media-stack/fix-jellyfin-sso-now.sh
```

### 3. Frontend Integration Documentation

Created `/docs/FRONTEND_JELLYFIN_SSO_INTEGRATION.md`:

**Covers**:
- ❌ Why hardcoding credentials is wrong
- ✅ 4 different SSO integration approaches:
  1. Web Browser SSO Flow (simplest)
  2. Mobile WebView approach
  3. Direct OIDC flow
  4. Backend proxy (most secure)
- 📝 Complete code examples for each approach
- 🔒 Security best practices
- 🧪 Testing instructions

### 4. Updated SSO Configuration

Files modified/created:
- ✅ `scripts/automation-media-stack/verify-and-fix-jellyfin-sso.py` - NEW
- ✅ `scripts/automation-media-stack/fix-jellyfin-sso-now.sh` - NEW
- ✅ `docs/FRONTEND_JELLYFIN_SSO_INTEGRATION.md` - NEW
- ✅ `docs/JELLYFIN_SSO_FIX_SUMMARY.md` - NEW (this file)

## 🚀 How to Fix Right Now

### Quick Fix (5 minutes)

1. **Run the fix script**:
```bash
cd /home/user/June
source config.env
bash scripts/automation-media-stack/fix-jellyfin-sso-now.sh
```

2. **If plugin not installed**, follow the output instructions:
   - Login to Jellyfin dashboard
   - Install SSO-Auth plugin
   - Run fix script again

3. **Update frontend code**:
   - Remove hardcoded credentials
   - Redirect users to: `https://tv.ozzu.world/sso/OID/start/keycloak`
   - See `docs/FRONTEND_JELLYFIN_SSO_INTEGRATION.md` for code examples

### Verification Checklist

After running the fix script:

- [ ] SSO plugin is installed in Jellyfin
- [ ] SSO configuration shows as enabled
- [ ] Can access `https://tv.ozzu.world/sso/OID/start/keycloak`
- [ ] Redirects to Keycloak login page
- [ ] After Keycloak login, redirects back to Jellyfin
- [ ] User can access Jellyfin without username/password
- [ ] Frontend no longer has hardcoded credentials
- [ ] Frontend redirects to SSO URL

## 📋 Frontend Action Items

### Immediate (CRITICAL)

1. **Remove Hardcoded Credentials**
   ```diff
   - const JELLYFIN_USER = "hadmin";
   - const JELLYFIN_PASS = "Pokemon123!";
   ```

2. **Implement SSO Redirect**
   ```javascript
   // For web apps
   function loginToJellyfin() {
     window.location.href = 'https://tv.ozzu.world/sso/OID/start/keycloak';
   }
   ```

3. **For Mobile Apps** - Use WebView approach (see docs)

### Short-term (This Sprint)

1. Implement proper SSO flow (see integration docs)
2. Handle Keycloak tokens correctly
3. Test SSO on all platforms (web, iOS, Android)

### Long-term (Production)

1. Implement backend proxy for better security
2. Add token refresh logic
3. Handle SSO errors gracefully
4. Add "Sign in with SSO" button to login screen

## 🔐 Security Improvements

### Before (INSECURE ❌)

```javascript
// Frontend code (EXPOSED TO USERS!)
const JELLYFIN_USERNAME = "hadmin";
const JELLYFIN_PASSWORD = "Pokemon123!";

fetch('https://tv.ozzu.world/Users/AuthenticateByName', {
  method: 'POST',
  body: JSON.stringify({
    Username: JELLYFIN_USERNAME,
    Pw: JELLYFIN_PASSWORD
  })
});
```

**Issues**:
- ❌ Credentials exposed in frontend code
- ❌ Anyone can extract credentials from app
- ❌ Bypasses SSO system
- ❌ Can't revoke access per-user
- ❌ No audit trail of who accessed what

### After (SECURE ✅)

```javascript
// Frontend code
function loginToJellyfin() {
  // Redirect to SSO
  window.location.href = 'https://tv.ozzu.world/sso/OID/start/keycloak';
}

// Jellyfin SSO plugin handles authentication
// User authenticates with Keycloak
// Keycloak validates user credentials
// Jellyfin creates session based on Keycloak token
// Frontend receives session cookie
```

**Benefits**:
- ✅ No credentials in frontend code
- ✅ Centralized authentication via Keycloak
- ✅ Per-user access control via roles
- ✅ Can revoke access in Keycloak
- ✅ Full audit trail
- ✅ Single Sign-On across all services

## 🧪 Testing

### Test SSO Manually

1. **Open Jellyfin**:
   ```
   https://tv.ozzu.world
   ```

2. **Click "Sign in with Keycloak SSO"** button

3. **Should redirect to**:
   ```
   https://idp.ozzu.world/realms/allsafe/protocol/openid-connect/auth?...
   ```

4. **Login with Keycloak credentials**

5. **Should redirect back to**:
   ```
   https://tv.ozzu.world
   ```

6. **Should be logged into Jellyfin** without entering Jellyfin credentials

### Test Programmatically

```bash
# Test SSO endpoint
curl -I -L "https://tv.ozzu.world/sso/OID/start/keycloak"

# Should see redirect to Keycloak
# HTTP/1.1 302 Found
# Location: https://idp.ozzu.world/realms/allsafe/protocol/openid-connect/auth...
```

## 📚 Documentation

All documentation is in the repository:

1. **Frontend Integration Guide**:
   `/docs/FRONTEND_JELLYFIN_SSO_INTEGRATION.md`
   - How to integrate SSO in frontend
   - Code examples for web and mobile
   - Backend proxy approach
   - Security best practices

2. **SSO Setup Scripts**:
   - `/scripts/automation-media-stack/fix-jellyfin-sso-now.sh` - One-command fix
   - `/scripts/automation-media-stack/verify-and-fix-jellyfin-sso.py` - Verification tool
   - `/scripts/automation-media-stack/provision-keycloak-media-sso.sh` - Keycloak setup
   - `/scripts/automation-media-stack/configure-jellyfin-sso.py` - Jellyfin config

3. **Original Setup Guide**:
   `/scripts/install/09.5-keycloak-media-sso.sh`

## 🎯 Success Criteria

SSO is working when:

- ✅ No hardcoded credentials in frontend
- ✅ Users can login via Keycloak
- ✅ SSO button visible on Jellyfin login page
- ✅ SSO endpoint redirects to Keycloak
- ✅ After Keycloak auth, user is logged into Jellyfin
- ✅ Roles from Keycloak properly map to Jellyfin permissions
- ✅ Verification script passes all checks

## 💡 Future Enhancements

1. **Automated Plugin Installation**
   - Explore Jellyfin API for plugin installation
   - Create Docker image with plugin pre-installed

2. **Health Monitoring**
   - Add SSO health check endpoint
   - Monitor SSO authentication success/failure rates
   - Alert on SSO issues

3. **User Onboarding**
   - Auto-assign roles based on email domain
   - Welcome email with SSO instructions
   - Self-service role requests

4. **Multi-Service SSO**
   - Extend to Jellyseerr (already has OIDC support)
   - Add SSO to other June platform services
   - Unified login experience

## 🆘 Troubleshooting

### Issue: SSO plugin not found

**Solution**: Install manually
```bash
# Login to Jellyfin dashboard
# Dashboard > Plugins > Repositories
# Add: https://raw.githubusercontent.com/9p4/jellyfin-plugin-sso/manifest-release/manifest.json
# Dashboard > Plugins > Catalog
# Install: SSO-Auth
# Restart Jellyfin
```

### Issue: SSO redirects but authentication fails

**Checks**:
- [ ] Client secret correct in Jellyfin SSO plugin
- [ ] User has `jellyfin-user` or `jellyfin-admin` role in Keycloak
- [ ] Redirect URLs match in Keycloak client configuration

### Issue: Frontend can't access Jellyfin after SSO

**Solutions**:
- Ensure frontend handles Jellyfin session cookies correctly
- Use `credentials: 'include'` in fetch requests
- For mobile apps, extract session token from WebView cookies

## 📞 Support

If issues persist:

1. **Check logs**:
   ```bash
   # Jellyfin logs
   kubectl logs -n media-stack deployment/jellyfin -f

   # Keycloak logs
   kubectl logs -n keycloak deployment/keycloak -f
   ```

2. **Run verification**:
   ```bash
   bash scripts/automation-media-stack/fix-jellyfin-sso-now.sh
   ```

3. **Review configuration**:
   ```bash
   source /tmp/media-sso-config.env
   echo "Jellyfin Client Secret: $JELLYFIN_CLIENT_SECRET"
   ```

---

**Status**: ✅ Fix implemented and ready to deploy
**Priority**: 🔴 Critical (security issue)
**Effort**: 🟢 Low (scripts provided, 5-15 minutes)
