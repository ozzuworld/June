# Headscale Architecture Issue - Important!

## ⚠️ The Real Problem

There's a **fundamental architectural mismatch** between what the frontend expects and how Headscale actually works.

### What the Frontend Expects (Traditional VPN)
```
Client ←WireGuard→ Central VPN Server
       (Headscale)
```

The frontend is trying to create a **traditional client-server VPN** where:
- One central server with a WireGuard public key
- Clients connect TO that server
- All traffic goes through the server

### How Headscale Actually Works (Mesh Network)
```
      Headscale (Control Server)
           ↓ ↓ ↓
         (coordinates)
           ↓ ↓ ↓
Client A ←→ Client B ←→ Client C
    (peer-to-peer WireGuard connections)
```

Headscale is a **mesh VPN control server** (like Tailscale):
- Headscale is a COORDINATION server, not a VPN gateway
- Clients register with Headscale and get IP addresses
- Clients connect **DIRECTLY to EACH OTHER** (peer-to-peer)
- No central VPN gateway by default
- Uses Noise protocol for control plane, not WireGuard server mode

## 🔍 Why `HEADSCALE_SERVER_PUBLIC_KEY` Doesn't Exist

**Headscale doesn't have a "server public key" in the traditional WireGuard sense** because:

1. **Headscale is not a WireGuard endpoint** - it's an HTTP/HTTPS control server
2. **Clients don't connect TO Headscale via WireGuard** - they connect to each other
3. **Headscale uses Noise protocol** for the control plane, not WireGuard
4. **Each client node has its own WireGuard keypair** for peer-to-peer connections

## ✅ Solutions

### Option 1: Use Tailscale/Headscale Client (Recommended)

**This is the intended way to use Headscale:**

```dart
// Instead of native WireGuard, use Tailscale client
import 'package:tailscale_dart/tailscale.dart';

// Connect using Headscale
await Tailscale.configure(
  controlURL: 'https://headscale.ozzu.world',
);

// Use the pre-auth key from backend
await Tailscale.up(authKey: response['pre_auth_key']);
```

**Pros:**
- ✅ Works with Headscale's architecture
- ✅ Automatic peer-to-peer mesh networking
- ✅ No need for server public key
- ✅ Access all nodes in the network

**Cons:**
- ❌ Need to use Tailscale client library
- ❌ No native WireGuard (but Tailscale uses WireGuard underneath)

### Option 2: Set Up an Exit Node (Traditional VPN Gateway)

If you really want traditional client-server VPN:

**Step 1: Deploy a WireGuard Gateway Node**

```yaml
# deploy-vpn-gateway.yaml
apiVersion: v1
kind: Pod
metadata:
  name: vpn-gateway
  namespace: headscale
spec:
  containers:
  - name: wireguard
    image: linuxserver/wireguard
    capabilities:
      add: ["NET_ADMIN", "SYS_MODULE"]
    env:
    - name: PUID
      value: "1000"
    - name: PGID
      value: "1000"
```

**Step 2: Register Gateway with Headscale**

```bash
# Install Tailscale on the gateway
tailscale up --login-server=https://headscale.ozzu.world \
  --advertise-exit-node

# Approve the exit node in Headscale
headscale routes enable -r <route-id>
```

**Step 3: Get Gateway's Public Key**

```bash
# On the gateway node
wg show | grep "public key"
```

**Step 4: Use Gateway's Key as `HEADSCALE_SERVER_PUBLIC_KEY`**

```bash
kubectl set env deployment/june-orchestrator -n june-services \
  HEADSCALE_SERVER_PUBLIC_KEY="<gateway-public-key>"
```

**Pros:**
- ✅ Traditional client-server VPN model
- ✅ Use native WireGuard on clients
- ✅ Central traffic routing through gateway

**Cons:**
- ❌ More complex setup (need gateway node)
- ❌ Single point of failure (gateway)
- ❌ Not using Headscale's mesh capabilities

### Option 3: Alternative - Use OpenVPN or Plain WireGuard

If the frontend team absolutely needs traditional client-server VPN:

**Consider using:**
- **WireGuard directly** (not through Headscale)
- **OpenVPN**
- **IPsec**

And keep Headscale for other use cases where mesh networking is beneficial.

## 🎯 Recommended Approach for Your Use Case

Based on your frontend's needs (native WireGuard config), I recommend:

### Short-term: Use Tailscale Client Library

```dart
// Frontend change needed
dependencies:
  tailscale_dart: ^0.1.0  # Or equivalent package

// Usage
final config = await api.registerDevice(token);
await Tailscale.configure(controlURL: config['login_server']);
await Tailscale.up(authKey: config['pre_auth_key']);
```

### Long-term: Deploy Exit Node Gateway

If you really need native WireGuard:

1. Deploy a WireGuard gateway pod in Kubernetes
2. Register it with Headscale as an exit node
3. Get the gateway's WireGuard public key
4. Set `HEADSCALE_SERVER_PUBLIC_KEY=<gateway-key>`
5. Update backend to return gateway's endpoint instead of Headscale URL

## 📊 Comparison

| Feature | Tailscale Client | Exit Node Gateway | Plain WireGuard |
|---------|-----------------|-------------------|-----------------|
| Setup Complexity | Low | Medium | Low |
| Mesh Networking | ✅ Yes | ❌ No | ❌ No |
| Native WireGuard | ❌ No | ✅ Yes | ✅ Yes |
| Headscale Integration | ✅ Perfect | ⚠️ Partial | ❌ None |
| Peer-to-Peer | ✅ Yes | ❌ No | ❌ No |
| Central Gateway | ❌ No | ✅ Yes | ✅ Yes |

## 🔧 What to Do Now

### Immediate Action

Run this script to verify Headscale's architecture:

```bash
cd /home/kazuma.ozzu/June
./scripts/extract-headscale-key.sh
```

This will show you that Headscale doesn't have a traditional "server public key".

### Decision Needed

**Ask your frontend team:**

1. **Can they use Tailscale client library?** (Easiest solution)
2. **Do they absolutely need native WireGuard?** (Need exit node gateway)
3. **Is mesh networking acceptable?** (Use Headscale as designed)

### If They Need Native WireGuard

I can help you:
1. Deploy a WireGuard exit node gateway
2. Register it with Headscale
3. Extract its public key
4. Update the backend to use gateway's key and endpoint

Let me know which direction you want to go!

## 📚 References

- [Headscale Documentation](https://github.com/juanfont/headscale)
- [Tailscale How It Works](https://tailscale.com/blog/how-tailscale-works/)
- [WireGuard Exit Nodes](https://tailscale.com/kb/1103/exit-nodes/)
