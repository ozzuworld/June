# Frontend Integration with Jellyfin SSO

## ❌ Problem: Hardcoded Credentials

The frontend should **NEVER** hardcode Jellyfin credentials. This is a security risk and bypasses the SSO system.

## ✅ Solution: Use Keycloak SSO Flow

### Architecture Overview

```
┌─────────────┐      ┌──────────────┐      ┌──────────────┐
│   Frontend  │─────>│   Keycloak   │─────>│   Jellyfin   │
│  (Mobile/Web)│<─────│  (SSO IdP)   │<─────│ (Media Server)│
└─────────────┘      └──────────────┘      └──────────────┘
```

### Authentication Flows

There are three ways your frontend can authenticate users with Jellyfin via SSO:

---

## Option 1: Web Browser SSO Flow (Recommended for Web)

This is the simplest approach for web frontends.

### How It Works

1. User clicks "Login" in your frontend
2. Frontend redirects to Jellyfin SSO URL
3. Jellyfin redirects to Keycloak
4. User authenticates with Keycloak
5. Keycloak redirects back to Jellyfin
6. Jellyfin creates session and redirects to your app

### Implementation

```javascript
// frontend/src/auth/jellyfin.js

const JELLYFIN_SSO_URL = 'https://tv.ozzu.world/sso/OID/start/keycloak';
const JELLYFIN_BASE_URL = 'https://tv.ozzu.world';

export function loginWithSSO() {
  // Simply redirect to Jellyfin SSO endpoint
  window.location.href = JELLYFIN_SSO_URL;
}

// After SSO completes, Jellyfin will set cookies
// Your app can then make authenticated API calls
export async function getCurrentUser() {
  const response = await fetch(`${JELLYFIN_BASE_URL}/Users/Me`, {
    credentials: 'include' // Include Jellyfin session cookies
  });

  if (response.ok) {
    return await response.json();
  }

  return null;
}

export async function getJellyfinAccessToken() {
  // If you need an API token for mobile apps
  // User must be already authenticated via SSO
  const response = await fetch(`${JELLYFIN_BASE_URL}/Users/Me`, {
    credentials: 'include',
    headers: {
      'X-Emby-Authorization': 'MediaBrowser Client="YourApp", Device="WebApp", DeviceId="unique-id", Version="1.0.0"'
    }
  });

  if (response.ok) {
    const data = await response.json();
    // Store data.AccessToken for API calls
    return data.AccessToken;
  }

  return null;
}
```

---

## Option 2: Mobile App with WebView (Recommended for Mobile)

For mobile apps, use an in-app browser to handle the SSO flow.

### Implementation (React Native Example)

```javascript
// mobile/src/auth/JellyfinSSO.js
import React, { useRef } from 'react';
import { WebView } from 'react-native-webview';

const JELLYFIN_SSO_URL = 'https://tv.ozzu.world/sso/OID/start/keycloak';
const JELLYFIN_BASE_URL = 'https://tv.ozzu.world';

export function JellyfinSSOLogin({ onSuccess, onError }) {
  const webViewRef = useRef(null);

  const handleNavigationStateChange = (navState) => {
    const { url } = navState;

    // Check if we've been redirected back to Jellyfin after SSO
    if (url.startsWith(JELLYFIN_BASE_URL) && !url.includes('/sso/')) {
      // SSO completed - extract session cookies
      webViewRef.current.injectJavaScript(`
        window.ReactNativeWebView.postMessage(JSON.stringify({
          cookies: document.cookie
        }));
      `);
    }
  };

  const handleMessage = async (event) => {
    try {
      const data = JSON.parse(event.nativeEvent.data);

      if (data.cookies) {
        // Parse Jellyfin session cookie
        const sessionMatch = data.cookies.match(/emby_session=([^;]+)/);

        if (sessionMatch) {
          const sessionToken = sessionMatch[1];

          // Store token securely
          await SecureStore.setItemAsync('jellyfin_session', sessionToken);

          // Get user info
          const user = await getJellyfinUser(sessionToken);

          onSuccess({ token: sessionToken, user });
        } else {
          onError(new Error('Session cookie not found'));
        }
      }
    } catch (err) {
      onError(err);
    }
  };

  return (
    <WebView
      ref={webViewRef}
      source={{ uri: JELLYFIN_SSO_URL }}
      onNavigationStateChange={handleNavigationStateChange}
      onMessage={handleMessage}
      sharedCookiesEnabled={true}
      thirdPartyCookiesEnabled={true}
    />
  );
}

async function getJellyfinUser(sessionToken) {
  const response = await fetch(`${JELLYFIN_BASE_URL}/Users/Me`, {
    headers: {
      'X-Emby-Token': sessionToken
    }
  });

  return await response.json();
}
```

---

## Option 3: Direct OIDC Flow (Advanced)

For native mobile apps that want full control, authenticate directly with Keycloak and exchange tokens.

### How It Works

1. Frontend authenticates user with Keycloak directly
2. Gets Keycloak access token
3. Uses Keycloak token to authenticate with Jellyfin via SSO plugin
4. Jellyfin validates token and creates session

### Implementation

```javascript
// frontend/src/auth/keycloak-direct.js

const KEYCLOAK_URL = 'https://idp.ozzu.world';
const REALM = 'allsafe';
const CLIENT_ID = 'june-mobile-app'; // Create this client in Keycloak

// 1. Authenticate with Keycloak using PKCE flow
export async function loginWithKeycloak() {
  // Use a library like @react-native-community/react-native-keycloak
  // or implement PKCE flow manually

  const keycloak = new Keycloak({
    url: KEYCLOAK_URL,
    realm: REALM,
    clientId: CLIENT_ID
  });

  await keycloak.login();

  return keycloak.token; // Keycloak access token
}

// 2. Use Keycloak token to get Jellyfin session
export async function exchangeKeycloakTokenForJellyfin(keycloakToken) {
  // The Jellyfin SSO plugin should accept Keycloak tokens
  // Check if Jellyfin SSO plugin supports token exchange endpoint

  const response = await fetch('https://tv.ozzu.world/sso/OID/p/keycloak', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${keycloakToken}`,
      'Content-Type': 'application/json'
    }
  });

  if (response.ok) {
    const data = await response.json();
    return data.AccessToken; // Jellyfin access token
  }

  throw new Error('Failed to exchange token');
}
```

**Note**: This requires the Jellyfin SSO plugin to support token exchange. Check the [plugin documentation](https://github.com/9p4/jellyfin-plugin-sso) for details.

---

## Option 4: Keycloak Native App (Most Secure)

For production mobile apps, create a dedicated Keycloak client.

### Setup

1. **Create Mobile App Client in Keycloak**:

```bash
# Run on server
cd /home/user/June
source config.env

# Create mobile client
curl -X POST "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "june-mobile-app",
    "enabled": true,
    "publicClient": true,
    "protocol": "openid-connect",
    "standardFlowEnabled": true,
    "redirectUris": ["juneapp://oauth/callback"],
    "webOrigins": ["*"]
  }'
```

2. **Implement PKCE Flow in Mobile App**:

```javascript
// mobile/src/auth/keycloak.js
import * as AuthSession from 'expo-auth-session';
import * as WebBrowser from 'expo-web-browser';

WebBrowser.maybeCompleteAuthSession();

const KEYCLOAK_URL = 'https://idp.ozzu.world';
const REALM = 'allsafe';
const CLIENT_ID = 'june-mobile-app';

const discovery = {
  authorizationEndpoint: `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/auth`,
  tokenEndpoint: `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token`,
};

export function useKeycloakAuth() {
  const [request, response, promptAsync] = AuthSession.useAuthRequest(
    {
      clientId: CLIENT_ID,
      scopes: ['openid', 'profile', 'email'],
      redirectUri: AuthSession.makeRedirectUri({
        scheme: 'juneapp'
      }),
    },
    discovery
  );

  React.useEffect(() => {
    if (response?.type === 'success') {
      const { code } = response.params;
      exchangeCodeForToken(code);
    }
  }, [response]);

  async function exchangeCodeForToken(code) {
    // Exchange authorization code for token
    const tokenResponse = await fetch(discovery.tokenEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: CLIENT_ID,
        code: code,
        redirect_uri: request.redirectUri,
        code_verifier: request.codeVerifier,
      }),
    });

    const tokens = await tokenResponse.json();

    // Now use tokens.access_token to access Jellyfin
    // The SSO plugin will validate this Keycloak token

    return tokens;
  }

  return { promptAsync, request };
}
```

3. **Access Jellyfin with Keycloak Token**:

```javascript
// After getting Keycloak token, access Jellyfin
export async function accessJellyfinWithKeycloakToken(accessToken) {
  // Option A: Go through SSO flow programmatically
  const jellyfinSession = await initiateJellyfinSSO(accessToken);

  // Option B: Use backend proxy that validates Keycloak token
  // and returns Jellyfin session
  const jellyfinSession = await yourBackend.getJellyfinSession(accessToken);

  return jellyfinSession;
}
```

---

## Backend Proxy Approach (Recommended for Production)

For better security and control, create a backend proxy service.

### Architecture

```
┌──────────┐    ┌─────────────┐    ┌──────────┐    ┌──────────┐
│ Frontend │───>│ Your Backend│───>│ Keycloak │    │ Jellyfin │
│          │<───│   Proxy     │<───│          │    │          │
└──────────┘    └─────────────┘    └──────────┘    └──────────┘
                       │                                  │
                       └──────────────────────────────────┘
```

### Backend Implementation

```python
# backend/jellyfin_proxy.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import requests
import jwt

app = FastAPI()
security = HTTPBearer()

KEYCLOAK_URL = "https://idp.ozzu.world"
REALM = "allsafe"
JELLYFIN_URL = "https://tv.ozzu.world"

def verify_keycloak_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify Keycloak JWT token"""
    token = credentials.credentials

    # Get Keycloak public key
    jwks_url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs"
    jwks = requests.get(jwks_url).json()

    # Verify token
    try:
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience="account",
            options={"verify_exp": True}
        )
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/api/jellyfin/authenticate")
async def get_jellyfin_session(user=Depends(verify_keycloak_token)):
    """
    Exchange Keycloak token for Jellyfin session.

    The frontend sends Keycloak token, backend validates it
    and returns a Jellyfin access token.
    """

    # Get or create Jellyfin user for this Keycloak user
    jellyfin_user = get_or_create_jellyfin_user(user)

    # Create Jellyfin session
    auth_response = requests.post(
        f"{JELLYFIN_URL}/Users/AuthenticateByName",
        json={
            "Username": jellyfin_user["Name"],
            # Use SSO plugin's authentication
        }
    )

    if auth_response.status_code == 200:
        return auth_response.json()

    raise HTTPException(status_code=401, detail="Jellyfin authentication failed")

@app.get("/api/jellyfin/proxy/{path:path}")
async def proxy_to_jellyfin(path: str, user=Depends(verify_keycloak_token)):
    """Proxy authenticated requests to Jellyfin"""

    # Validate Keycloak token and get Jellyfin session
    jellyfin_token = get_jellyfin_token_for_user(user["sub"])

    # Forward request to Jellyfin
    response = requests.get(
        f"{JELLYFIN_URL}/{path}",
        headers={"X-Emby-Token": jellyfin_token}
    )

    return response.json()
```

### Frontend with Backend Proxy

```javascript
// frontend/src/api/jellyfin.js

const BACKEND_URL = 'https://api.ozzu.world';
const JELLYFIN_URL = 'https://tv.ozzu.world';

export class JellyfinClient {
  constructor(keycloakToken) {
    this.keycloakToken = keycloakToken;
    this.jellyfinToken = null;
  }

  async authenticate() {
    // Exchange Keycloak token for Jellyfin session via backend
    const response = await fetch(`${BACKEND_URL}/api/jellyfin/authenticate`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.keycloakToken}`
      }
    });

    const data = await response.json();
    this.jellyfinToken = data.AccessToken;

    return data;
  }

  async getLibraries() {
    // Use backend proxy
    const response = await fetch(`${BACKEND_URL}/api/jellyfin/proxy/Users/Me/Views`, {
      headers: {
        'Authorization': `Bearer ${this.keycloakToken}`
      }
    });

    return await response.json();
  }

  // Or call Jellyfin directly with token
  async getDirectly(endpoint) {
    if (!this.jellyfinToken) {
      await this.authenticate();
    }

    const response = await fetch(`${JELLYFIN_URL}/${endpoint}`, {
      headers: {
        'X-Emby-Token': this.jellyfinToken
      }
    });

    return await response.json();
  }
}
```

---

## Summary: Remove Hardcoded Credentials

### What To Do

1. **Remove hardcoded credentials** from frontend code immediately
2. **Choose an integration approach** from the options above
3. **For quick fix**: Use Option 1 (Web Browser SSO Flow) - just redirect to SSO URL
4. **For production**: Use Option 4 (Backend Proxy) for better security

### Testing the SSO Flow

```bash
# Verify SSO is working
cd /home/user/June
python3 scripts/automation-media-stack/verify-and-fix-jellyfin-sso.py \
  --jellyfin-url "https://tv.ozzu.world" \
  --username "$JELLYFIN_USERNAME" \
  --password "$JELLYFIN_PASSWORD" \
  --keycloak-url "$KEYCLOAK_URL" \
  --realm "$KEYCLOAK_REALM" \
  --domain "$DOMAIN" \
  --fix
```

### Frontend Checklist

- [ ] Remove hardcoded `JELLYFIN_USERNAME` and `JELLYFIN_PASSWORD`
- [ ] Implement SSO redirect or WebView flow
- [ ] Use Keycloak tokens for authentication
- [ ] Store tokens securely (iOS Keychain, Android KeyStore, SecureStore)
- [ ] Handle token refresh
- [ ] Test SSO login flow end-to-end

---

## Need Help?

If you encounter issues:

1. **Check SSO Plugin**: Ensure `SSO-Auth` plugin is installed in Jellyfin
2. **Verify Keycloak Client**: Ensure `jellyfin` client exists in Keycloak realm
3. **Check User Roles**: Users need `jellyfin-user` or `jellyfin-admin` role in Keycloak
4. **Test SSO URL**: Visit `https://tv.ozzu.world/sso/OID/start/keycloak` in browser

For detailed debugging:

```bash
# Check Jellyfin logs
kubectl logs -n media-stack deployment/jellyfin -f

# Check Keycloak logs
kubectl logs -n keycloak deployment/keycloak -f
```
