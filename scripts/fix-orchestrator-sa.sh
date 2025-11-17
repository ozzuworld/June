#!/bin/bash
# Force fix the ServiceAccount for june-orchestrator

set -e

echo "🔧 Forcing ServiceAccount update for june-orchestrator..."
echo ""

# First, verify the deployment spec
echo "1️⃣ Current deployment spec ServiceAccount:"
CURRENT_SA=$(kubectl get deployment june-orchestrator -n june-services -o jsonpath='{.spec.template.spec.serviceAccountName}')
echo "   $CURRENT_SA"
echo ""

if [ "$CURRENT_SA" = "june-orchestrator" ]; then
    echo "✅ Deployment spec is correct, but pods might be old."
    echo "   Deleting old pods to force recreation..."
    echo ""
    kubectl delete pods -n june-services -l app=june-orchestrator
    echo ""
    echo "⏳ Waiting for new pods to start..."
    sleep 10
else
    echo "❌ Deployment spec is wrong. Patching..."
    echo ""

    # Patch the deployment
    kubectl patch deployment june-orchestrator -n june-services \
      --type='strategic' \
      -p '{"spec":{"template":{"spec":{"serviceAccountName":"june-orchestrator"}}}}'

    echo ""
    echo "✅ Deployment patched. Waiting for rollout..."
fi

# Wait for rollout
kubectl rollout status deployment/june-orchestrator -n june-services --timeout=120s

echo ""
echo "2️⃣ Verifying new pods..."
echo ""

# Get the new pod
sleep 5
POD=$(kubectl get pod -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}')
SA=$(kubectl get pod -n june-services $POD -o jsonpath='{.spec.serviceAccountName}')

echo "Pod name: $POD"
echo "Pod ServiceAccount: $SA"
echo ""

if [ "$SA" = "june-orchestrator" ]; then
    echo "✅ SUCCESS! Pod is using correct ServiceAccount: $SA"
    echo ""
    echo "3️⃣ Testing RBAC permissions..."
    echo ""
    kubectl exec -n june-services $POD -- kubectl get pods -n headscale 2>&1 | head -10
    echo ""
    echo "🎉 If you see headscale pods listed above, RBAC is working!"
else
    echo "❌ FAILED! Pod is still using: $SA"
    echo ""
    echo "Debug info:"
    echo "Deployment spec:"
    kubectl get deployment june-orchestrator -n june-services -o yaml | grep -A 5 "serviceAccountName"
    echo ""
    echo "Pod spec:"
    kubectl get pod $POD -n june-services -o yaml | grep -A 2 "serviceAccountName"
    exit 1
fi
