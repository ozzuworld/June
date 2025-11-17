#!/bin/bash
# Extract Headscale server's WireGuard public key

set -e

echo "🔍 Looking for Headscale server public key..."
echo ""

# Method 1: Check Headscale pod's WireGuard interface
echo "Method 1: Checking WireGuard interface in Headscale pod..."
POD=$(kubectl get pod -n headscale -l app=headscale -o jsonpath='{.items[0].metadata.name}')

if [ -n "$POD" ]; then
    echo "Found Headscale pod: $POD"
    echo ""

    # Try to get the public key from wg command
    echo "Trying 'wg show' command..."
    kubectl exec -n headscale $POD -- wg show 2>/dev/null || echo "wg command not available"
    echo ""

    # Try to get it from the config
    echo "Method 2: Checking Headscale configuration..."
    kubectl exec -n headscale $POD -- cat /etc/headscale/config.yaml 2>/dev/null | grep -A 5 "private_key" || echo "Config not accessible"
    echo ""

    # Try headscale CLI
    echo "Method 3: Using Headscale debug commands..."
    kubectl exec -n headscale $POD -- headscale debug dump-config 2>/dev/null | grep -i "private_key" || echo "Debug command failed"
    echo ""

    # Check if there's a derp configuration
    echo "Method 4: Checking DERP configuration..."
    kubectl exec -n headscale $POD -- headscale debug dump-config 2>/dev/null | grep -A 10 "derp" | head -20 || echo "No DERP config found"
    echo ""

    # List all nodes - sometimes the server key is visible there
    echo "Method 5: Checking nodes list..."
    kubectl exec -n headscale $POD -- headscale nodes list --output json 2>/dev/null | head -50 || echo "Nodes list failed"
    echo ""

    # Check ConfigMap
    echo "Method 6: Checking ConfigMap..."
    kubectl get configmap -n headscale headscale-config -o yaml 2>/dev/null | grep -A 5 "server_url" || echo "No ConfigMap found"
    echo ""

    # Check for WireGuard keys in the filesystem
    echo "Method 7: Looking for key files..."
    kubectl exec -n headscale $POD -- find /etc/headscale /var/lib/headscale -name "*.key" -o -name "*private*" -o -name "*public*" 2>/dev/null | head -10 || echo "No key files found"
    echo ""
else
    echo "❌ No Headscale pod found!"
    exit 1
fi

echo ""
echo "📋 Summary:"
echo "The Headscale server public key is the WireGuard public key that"
echo "Headscale uses for its VPN server. Look for:"
echo "  - A 44-character base64 string"
echo "  - In Headscale config under 'noise' or 'private_key_path'"
echo "  - From 'wg show' output if WireGuard is running"
echo "  - In environment variables or secrets"
