#!/bin/bash
# Apply RBAC permissions for orchestrator to exec into Headscale pods

set -e

echo "🔐 Applying RBAC permissions for june-orchestrator..."
echo ""

# Apply the RBAC resources
kubectl apply -f k8s/rbac/orchestrator-headscale-access-complete.yaml

echo ""
echo "✅ RBAC resources created:"
echo "   - ServiceAccount: june-orchestrator (in june-services namespace)"
echo "   - Role: headscale-exec (in headscale namespace)"
echo "   - RoleBinding: june-orchestrator-headscale-exec"
echo ""

# Patch the existing deployment to use the new ServiceAccount
echo "🔄 Patching deployment to use ServiceAccount..."
kubectl patch deployment june-orchestrator -n june-services \
  -p '{"spec":{"template":{"spec":{"serviceAccountName":"june-orchestrator"}}}}'

echo ""
echo "⏳ Waiting for rollout to complete..."
kubectl rollout status deployment/june-orchestrator -n june-services --timeout=120s

echo ""
echo "✅ Deployment updated successfully!"
echo ""

# Verify the ServiceAccount is being used
echo "🔍 Verifying ServiceAccount..."
POD=$(kubectl get pod -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}')
SA=$(kubectl get pod -n june-services $POD -o jsonpath='{.spec.serviceAccountName}')

if [ "$SA" = "june-orchestrator" ]; then
    echo "✅ Pod is using correct ServiceAccount: $SA"
else
    echo "❌ ERROR: Pod is using wrong ServiceAccount: $SA"
    exit 1
fi

echo ""
echo "🧪 Testing RBAC permissions..."

# Test if the pod can now access Headscale pods
kubectl exec -n june-services $POD -- kubectl get pods -n headscale 2>&1 | head -5

echo ""
echo "🎉 RBAC setup complete! The orchestrator can now:"
echo "   ✓ List pods in headscale namespace"
echo "   ✓ Exec into headscale pods"
echo "   ✓ Create Headscale users via CLI"
echo "   ✓ Generate pre-auth keys via CLI"
echo ""
echo "📝 Try the VPN registration endpoint again:"
echo "   POST https://api.ozzu.world/api/v1/device/register"
