# Frontend Team: VPN Integration Guide

## Overview

This guide explains how to integrate **seamless VPN authentication** into the mobile/web app using Keycloak SSO and Headscale VPN.

**The Goal**: User logs in once with Keycloak → Automatically connects to VPN with the same credentials → No second login needed!

---

## 🎯 User Experience Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: User Opens App                                     │
│  ├─ User sees "Login" button                                │
│  └─ User taps "Login"                                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 2: Keycloak Authentication                            │
│  ├─ App opens Keycloak login page                           │
│  ├─ User enters email/password                              │
│  ├─ Keycloak authenticates                                  │
│  └─ App receives access token + user info                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 3: User Sees Home Screen                              │
│  ├─ App shows: "Welcome, user@ozzu.world"                   │
│  ├─ App shows VPN toggle: "Connect to VPN"                  │
│  └─ User taps "Connect to VPN"                              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 4: VPN Connection (Automatic!)                        │
│  ├─ App calls Tailscale SDK with Headscale server           │
│  ├─ SDK opens browser for OIDC authentication               │
│  ├─ **Keycloak recognizes existing session (same user!)**   │
│  ├─ **NO LOGIN PROMPT - auto-approves!**                    │
│  ├─ Headscale receives OIDC token from Keycloak             │
│  ├─ Headscale registers device                              │
│  └─ VPN connected! ✅                                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 5: User is Connected                                  │
│  ├─ App shows: "VPN: Connected ✅"                           │
│  ├─ User can now access private resources                   │
│  └─ All traffic routes through VPN                          │
└─────────────────────────────────────────────────────────────┘
```

**Key Point**: Steps 2 and 4 use the **same Keycloak session**, so the VPN connection happens without a second login!

---

## 🔧 Technical Architecture

### Backend Components (Already Setup)

- **Keycloak**: `https://idp.ozzu.world` (Realm: `allsafe`)
  - Client for app: `june-mobile-app` (PKCE public client)
  - Client for VPN: `headscale-vpn` (OIDC confidential client)

- **Headscale VPN**: `https://headscale.ozzu.world`
  - OIDC-enabled
  - Uses Keycloak for authentication
  - Auto-registers devices

### Frontend Integration Points

1. **App Authentication**: Keycloak OIDC via `june-mobile-app` client
2. **VPN Authentication**: Headscale OIDC via same Keycloak session

---

## 📱 Implementation Guide

### Step 1: Install Dependencies

**React Native:**
```bash
npm install @react-native-community/netinfo
npm install react-native-app-auth
# For VPN (if using native Tailscale integration)
# Note: Tailscale doesn't have official RN package, you'll need native modules or web approach
```

**Expo (Managed Workflow):**
```bash
npx expo install expo-auth-session expo-web-browser
npx expo install @react-native-community/netinfo
```

### Step 2: Configure Keycloak Authentication

Create `src/services/auth.ts`:

```typescript
import * as AuthSession from 'expo-auth-session';
import * as WebBrowser from 'expo-web-browser';

// Enable browser session sharing (crucial for SSO!)
WebBrowser.maybeCompleteAuthSession();

const KEYCLOAK_URL = 'https://idp.ozzu.world';
const REALM = 'allsafe';
const CLIENT_ID = 'june-mobile-app'; // PKCE public client

const discovery = {
  authorizationEndpoint: `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/auth`,
  tokenEndpoint: `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token`,
  revocationEndpoint: `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/logout`,
};

export const useKeycloakAuth = () => {
  const [request, response, promptAsync] = AuthSession.useAuthRequest(
    {
      clientId: CLIENT_ID,
      scopes: ['openid', 'profile', 'email'],
      redirectUri: AuthSession.makeRedirectUri({
        scheme: 'june',
        path: 'auth/callback',
      }),
      usePKCE: true, // Enable PKCE for security
    },
    discovery
  );

  return { request, response, promptAsync };
};

export const loginWithKeycloak = async (promptAsync: () => Promise<any>) => {
  try {
    const result = await promptAsync();

    if (result.type === 'success') {
      const { authentication } = result;
      // Store tokens securely
      await SecureStore.setItemAsync('access_token', authentication.accessToken);
      await SecureStore.setItemAsync('refresh_token', authentication.refreshToken);

      // Fetch user info
      const userInfo = await fetchUserInfo(authentication.accessToken);
      return { success: true, user: userInfo };
    }

    return { success: false, error: 'Authentication cancelled' };
  } catch (error) {
    return { success: false, error: error.message };
  }
};

const fetchUserInfo = async (accessToken: string) => {
  const response = await fetch(
    `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/userinfo`,
    {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    }
  );
  return response.json();
};
```

### Step 3: Implement VPN Connection

**Option A: Using WebView/Browser (Recommended - Works on all platforms)**

Create `src/services/vpn.ts`:

```typescript
import * as WebBrowser from 'expo-web-browser';
import { Linking } from 'react-native';

const HEADSCALE_URL = 'https://headscale.ozzu.world';

export const connectToVPN = async () => {
  try {
    // The magic happens here: Open Headscale OIDC login in same browser context
    // Since user is already logged into Keycloak, this will use existing session!

    const authUrl = `${HEADSCALE_URL}/oidc/register`;

    // Open in browser - Keycloak will recognize the existing session
    const result = await WebBrowser.openAuthSessionAsync(
      authUrl,
      'june://vpn/callback'
    );

    if (result.type === 'success') {
      // VPN registration complete
      // The device is now registered with Headscale
      return { success: true, message: 'VPN connected!' };
    }

    return { success: false, error: 'VPN connection cancelled' };
  } catch (error) {
    console.error('VPN connection error:', error);
    return { success: false, error: error.message };
  }
};

export const disconnectFromVPN = async () => {
  // Implement VPN disconnect logic
  // This might require native modules or API calls
};

export const getVPNStatus = async () => {
  // Check if VPN is connected
  // Return connection status and IP
};
```

**Option B: Using Native Tailscale SDK (iOS/Android)**

For native integration, you'll need to create native modules:

**iOS (Swift):**
```swift
// ios/VPNManager.swift
import Foundation
import NetworkExtension

@objc(VPNManager)
class VPNManager: NSObject {

  @objc
  func connectToHeadscale(_ controlURL: String,
                          resolver: @escaping RCTPromiseResolveBlock,
                          rejecter: @escaping RCTPromiseRejectBlock) {
    // Configure Tailscale/WireGuard with custom control server
    // This requires Tailscale SDK or WireGuard implementation

    // The OIDC flow will happen automatically when connecting
    // Browser opens -> Keycloak recognizes session -> Auto-approves

    resolver(["status": "connected"])
  }

  @objc
  static func requiresMainQueueSetup() -> Bool {
    return true
  }
}
```

**Android (Kotlin):**
```kotlin
// android/app/src/main/java/VPNManager.kt
package com.yourapp

import com.facebook.react.bridge.*

class VPNManager(reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext) {

  override fun getName(): String {
    return "VPNManager"
  }

  @ReactMethod
  fun connectToHeadscale(controlURL: String, promise: Promise) {
    // Implement Tailscale/WireGuard connection
    // with custom control server

    try {
      // OIDC flow happens via browser intent
      // Keycloak session is shared with browser
      promise.resolve(mapOf("status" to "connected"))
    } catch (e: Exception) {
      promise.reject("VPN_ERROR", e.message)
    }
  }
}
```

### Step 4: Create VPN UI Component

Create `src/components/VPNToggle.tsx`:

```typescript
import React, { useState, useEffect } from 'react';
import { View, Text, Switch, ActivityIndicator, Alert } from 'react-native';
import { connectToVPN, disconnectFromVPN, getVPNStatus } from '../services/vpn';

export const VPNToggle = () => {
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [vpnIP, setVpnIP] = useState(null);

  useEffect(() => {
    checkVPNStatus();
  }, []);

  const checkVPNStatus = async () => {
    const status = await getVPNStatus();
    setIsConnected(status.connected);
    setVpnIP(status.ip);
  };

  const handleToggle = async (value: boolean) => {
    setIsLoading(true);

    try {
      if (value) {
        // Connect to VPN
        const result = await connectToVPN();

        if (result.success) {
          setIsConnected(true);
          Alert.alert('Success', 'VPN connected!');
          checkVPNStatus();
        } else {
          Alert.alert('Error', result.error || 'Failed to connect to VPN');
        }
      } else {
        // Disconnect from VPN
        await disconnectFromVPN();
        setIsConnected(false);
        setVpnIP(null);
      }
    } catch (error) {
      Alert.alert('Error', error.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.row}>
        <View>
          <Text style={styles.title}>VPN Connection</Text>
          {isConnected && vpnIP && (
            <Text style={styles.subtitle}>IP: {vpnIP}</Text>
          )}
        </View>

        {isLoading ? (
          <ActivityIndicator />
        ) : (
          <Switch
            value={isConnected}
            onValueChange={handleToggle}
            trackColor={{ false: '#767577', true: '#81b0ff' }}
            thumbColor={isConnected ? '#0066ff' : '#f4f3f4'}
          />
        )}
      </View>

      {isConnected && (
        <View style={styles.statusBadge}>
          <View style={styles.greenDot} />
          <Text style={styles.statusText}>Connected</Text>
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    padding: 16,
    backgroundColor: '#f5f5f5',
    borderRadius: 12,
    marginVertical: 8,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  title: {
    fontSize: 16,
    fontWeight: '600',
  },
  subtitle: {
    fontSize: 12,
    color: '#666',
    marginTop: 4,
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 12,
  },
  greenDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#00cc00',
    marginRight: 8,
  },
  statusText: {
    fontSize: 14,
    color: '#00cc00',
  },
});
```

### Step 5: Integrate into Main App

Create `src/screens/HomeScreen.tsx`:

```typescript
import React, { useEffect, useState } from 'react';
import { View, Text, Button } from 'react-native';
import { VPNToggle } from '../components/VPNToggle';
import { useKeycloakAuth, loginWithKeycloak } from '../services/auth';
import * as SecureStore from 'expo-secure-store';

export const HomeScreen = () => {
  const [user, setUser] = useState(null);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const { promptAsync } = useKeycloakAuth();

  useEffect(() => {
    checkLoginStatus();
  }, []);

  const checkLoginStatus = async () => {
    const token = await SecureStore.getItemAsync('access_token');
    if (token) {
      // Fetch user info and set logged in
      setIsLoggedIn(true);
      // TODO: Fetch and set user
    }
  };

  const handleLogin = async () => {
    const result = await loginWithKeycloak(promptAsync);
    if (result.success) {
      setUser(result.user);
      setIsLoggedIn(true);
    }
  };

  const handleLogout = async () => {
    await SecureStore.deleteItemAsync('access_token');
    await SecureStore.deleteItemAsync('refresh_token');
    setUser(null);
    setIsLoggedIn(false);
  };

  if (!isLoggedIn) {
    return (
      <View style={styles.container}>
        <Text style={styles.title}>Welcome to June</Text>
        <Button title="Login with Keycloak" onPress={handleLogin} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Welcome, {user?.email || 'User'}!</Text>

      {/* VPN Toggle - Uses same Keycloak session! */}
      <VPNToggle />

      <Button title="Logout" onPress={handleLogout} />
    </View>
  );
};
```

---

## 🔑 Key Technical Details

### Why Does Seamless SSO Work?

1. **Shared Browser Session**: When the app opens Keycloak login using `WebBrowser.openAuthSessionAsync()`, it uses the system browser
2. **Session Cookie**: Keycloak sets a session cookie in the browser after first login
3. **Second OIDC Flow**: When VPN connection triggers Headscale OIDC, it opens the browser again
4. **Auto-Approval**: Keycloak sees the existing session cookie and **automatically approves without prompting user**
5. **Token Issued**: Keycloak issues token to Headscale, device registers, VPN connects!

### Authentication Flow Diagram

```
App Login (Step 1):
┌──────┐    OIDC Request    ┌──────────┐   Authenticates   ┌──────────┐
│ App  │ ─────────────────> │ Keycloak │ ────────────────> │ User     │
└──────┘                    └──────────┘                   └──────────┘
   ↑                             │
   │         Access Token        │
   │    + Session Cookie Set     │
   └─────────────────────────────┘

VPN Connect (Step 2):
┌──────┐    OIDC Request    ┌───────────┐   Uses Cookie    ┌──────────┐
│ VPN  │ ─────────────────> │ Keycloak  │ ────────────────>│ Session  │
│ SDK  │                    └───────────┘  (no prompt!)    └──────────┘
└──────┘                         │
   ↑                             │
   │         OIDC Token          │
   │     (auto-approved)         │
   └─────────────────────────────┘
```

---

## 🧪 Testing the Integration

### Test Scenario 1: Fresh Login

1. User opens app (not logged in)
2. Tap "Login" → Keycloak page opens
3. Enter credentials → Login successful
4. App shows home screen
5. Toggle VPN on → Browser opens briefly
6. **Browser auto-closes (no login prompt!)**
7. VPN connected!

### Test Scenario 2: Already Logged In

1. User opens app (already logged in)
2. App shows home screen immediately
3. Toggle VPN on → Browser opens briefly
4. **Browser auto-closes (no login prompt!)**
5. VPN connected!

### Test Scenario 3: Session Expired

1. User opens app after token expiry
2. App shows login button
3. User logs in again
4. VPN toggle works with new session

---

## 📊 Configuration Summary

### Keycloak Clients

**june-mobile-app** (For app authentication):
- Type: Public client (PKCE)
- Redirect URI: `june://auth/callback`
- Scopes: `openid`, `profile`, `email`

**headscale-vpn** (For VPN authentication):
- Type: Confidential client (OIDC)
- Redirect URI: `https://headscale.ozzu.world/oidc/callback`
- Scopes: `openid`, `profile`, `email`

### URLs You'll Need

```typescript
// Environment config
export const CONFIG = {
  KEYCLOAK_URL: 'https://idp.ozzu.world',
  KEYCLOAK_REALM: 'allsafe',
  KEYCLOAK_CLIENT_ID: 'june-mobile-app',
  HEADSCALE_URL: 'https://headscale.ozzu.world',
  API_URL: 'https://api.ozzu.world',
};
```

---

## 🚨 Common Issues & Solutions

### Issue 1: Browser doesn't recognize session

**Symptom**: VPN connection prompts for login again

**Solution**: Ensure you're using `WebBrowser.openAuthSessionAsync()` not `Linking.openURL()`. The former shares cookies with the system browser.

### Issue 2: PKCE verification failed

**Symptom**: Error during Keycloak authentication

**Solution**: Ensure `usePKCE: true` is set in auth request configuration.

### Issue 3: VPN connects but can't access resources

**Symptom**: VPN shows connected but can't reach internal services

**Solution**: Check Headscale ACL policies allow the user's device to access resources.

### Issue 4: iOS doesn't save session

**Symptom**: Works on Android but not iOS

**Solution**: Enable "Shared Web Credentials" in Xcode capabilities.

---

## 🎯 Implementation Checklist

- [ ] Install required dependencies
- [ ] Configure Keycloak authentication with PKCE
- [ ] Test app login flow
- [ ] Implement VPN connection service
- [ ] Create VPN toggle UI component
- [ ] Test seamless SSO (no second login)
- [ ] Handle token refresh
- [ ] Add VPN status indicators
- [ ] Test on both iOS and Android
- [ ] Handle network errors gracefully
- [ ] Add analytics/logging
- [ ] Document for other team members

---

## 📞 Support & Questions

**Backend Team Contact**: [Your name]
**Keycloak Admin**: https://idp.ozzu.world
**Headscale Dashboard**: `kubectl exec -n headscale deployment/headscale -- headscale nodes list`

**Test Credentials**:
- Create test users in Keycloak admin console
- Users must have verified email for VPN access

---

## 🚀 Next Steps

1. **Phase 1**: Implement Keycloak login (Week 1)
2. **Phase 2**: Add VPN connection (Week 2)
3. **Phase 3**: Test seamless SSO flow (Week 2)
4. **Phase 4**: Polish UI/UX (Week 3)
5. **Phase 5**: Production testing (Week 3-4)

**Good luck! The backend is ready and waiting for your integration!** 🎉
