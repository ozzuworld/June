#!/bin/bash
# Simple script to extract Headscale server's public key

echo "🔍 Extracting Headscale server public key..."
echo ""

# Get Headscale pod
POD=$(kubectl get pod -n headscale -l app=headscale -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD" ]; then
    echo "❌ No Headscale pod found!"
    exit 1
fi

echo "✅ Found Headscale pod: $POD"
echo ""

# Get the noise private key path from config
echo "📄 Getting Headscale configuration..."
CONFIG=$(kubectl exec -n headscale $POD -- headscale debug dump-config 2>/dev/null)

# Check if we got the config
if [ -z "$CONFIG" ]; then
    echo "❌ Could not get Headscale config"
    exit 1
fi

echo "✅ Retrieved Headscale config"
echo ""

# Extract noise private key path
NOISE_KEY_PATH=$(echo "$CONFIG" | grep "private_key_path" | head -1 | awk '{print $2}' | tr -d '"' | tr -d "'")

if [ -n "$NOISE_KEY_PATH" ]; then
    echo "📍 Noise private key path: $NOISE_KEY_PATH"
    echo ""

    # Try to read the private key file and derive public key
    echo "🔐 Reading private key..."
    PRIV_KEY=$(kubectl exec -n headscale $POD -- cat "$NOISE_KEY_PATH" 2>/dev/null)

    if [ -n "$PRIV_KEY" ]; then
        echo "✅ Found private key"
        echo ""
        echo "⚠️  IMPORTANT:"
        echo "The Noise protocol private key cannot be directly converted to a WireGuard public key."
        echo "Headscale uses Noise protocol, not traditional WireGuard server mode."
        echo ""
    fi
fi

# Check server_url
echo "🌐 Headscale server URL:"
echo "$CONFIG" | grep "server_url" | head -1
echo ""

# Check listen address
echo "📡 Headscale listen address:"
echo "$CONFIG" | grep "listen_addr" | head -1
echo ""

# Important note about Headscale architecture
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚠️  IMPORTANT INFORMATION ABOUT HEADSCALE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Headscale is a CONTROL SERVER for mesh VPN networks (like Tailscale)."
echo "It is NOT a traditional WireGuard server that clients connect to directly."
echo ""
echo "In a mesh network:"
echo "  • Clients register with Headscale (control plane)"
echo "  • Clients get IP addresses from Headscale"
echo "  • Clients connect DIRECTLY to EACH OTHER (peer-to-peer)"
echo "  • No central VPN gateway by default"
echo ""
echo "If you want a traditional client-server VPN:"
echo "  1. Set up a WireGuard gateway node"
echo "  2. Register that gateway with Headscale"
echo "  3. Configure it as an exit node"
echo "  4. Get that gateway's public key"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if there's an exit node configured
echo "🚪 Checking for exit nodes..."
kubectl exec -n headscale $POD -- headscale routes list 2>/dev/null || echo "No routes configured"
echo ""

echo "💡 SOLUTION:"
echo ""
echo "Option 1: Use Tailscale client with pre-auth key"
echo "  - Clients use Tailscale/Headscale client app"
echo "  - Connect using the pre-auth key we generate"
echo "  - Mesh network, no central server needed"
echo ""
echo "Option 2: Set up exit node for traditional VPN"
echo "  - Deploy a WireGuard gateway as a Headscale node"
echo "  - Configure it as an exit node"
echo "  - Use that node's public key as serverPublicKey"
echo ""
