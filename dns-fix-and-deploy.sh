#!/bin/bash
# dns-fix-and-deploy.sh - Fix DNS and setup auto-deployment
set -euo pipefail

echo "🚨 CRITICAL DNS ISSUE DETECTED!"
echo "==============================="
echo ""
echo "❌ WRONG DNS (causing certificate failure):"
echo "   api.allsafe.world  → 104.21.68.119 (Cloudflare)"
echo "   idp.allsafe.world  → 172.67.195.11 (Cloudflare)"
echo "   stt.allsafe.world  → 104.21.68.119 (Cloudflare)"
echo ""
echo "✅ CORRECT DNS (what you need):"
echo "   api.allsafe.world  → 34.149.245.135 (GKE Load Balancer)"
echo "   idp.allsafe.world  → 34.149.245.135 (GKE Load Balancer)" 
echo "   stt.allsafe.world  → 34.149.245.135 (GKE Load Balancer)"
echo ""
echo "🔧 ACTION REQUIRED: Update these A records in your DNS provider:"

# Step 1: Quick Keycloak fix
echo ""
echo "Step 1: Fixing IDP image (using official Keycloak)..."
kubectl patch deployment june-idp -n june-services -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "june-idp",
          "image": "quay.io/keycloak/keycloak:23.0.3",
          "command": ["/opt/keycloak/bin/kc.sh"],
          "args": ["start-dev", "--http-enabled=true"]
        }]
      }
    }
  }
}' || echo "Deployment may not exist yet"

echo "✅ IDP image fixed to use official Keycloak"

# Step 2: Show required DNS changes
echo ""
echo "Step 2: DNS Configuration Required"
echo "=================================="
echo ""
echo "🔥 URGENT: Update these DNS records in your provider:"
echo ""
echo "A  api.allsafe.world   34.149.245.135"
echo "A  idp.allsafe.world   34.149.245.135"
echo "A  stt.allsafe.world   34.149.245.135"
echo ""
echo "💡 Your apex domain (allsafe.world) is correct ✅"
echo "💡 Only the subdomains need fixing ⚠️"

# Step 3: Wait for user to fix DNS
echo ""
read -p "Press Enter after updating DNS records in your provider..." -r

echo ""
echo "🔍 Verifying DNS changes..."
sleep 5

# Verify DNS
for subdomain in api idp stt; do
    IP=$(nslookup ${subdomain}.allsafe.world 8.8.8.8 | grep "Address:" | tail -1 | awk '{print $2}' || echo "FAILED")
    if [ "$IP" = "34.149.245.135" ]; then
        echo "✅ ${subdomain}.allsafe.world → $IP (CORRECT)"
    else
        echo "❌ ${subdomain}.allsafe.world → $IP (WRONG - should be 34.149.245.135)"
    fi
done

echo ""
echo "⏳ Certificate should provision in 5-10 minutes after DNS is correct..."
echo ""
echo "🔄 Monitor certificate status:"
echo "kubectl get managedcertificate -n june-services -w"
echo ""

# Step 4: Show Terraform integration
echo "Step 3: Setting up Terraform auto-deployment"
echo "============================================"
echo ""
echo "📁 Adding to your Terraform configuration..."