#!/bin/bash
# Check if june-orchestrator is using the correct ServiceAccount

echo "🔍 Checking june-orchestrator ServiceAccount configuration..."
echo ""

echo "1️⃣ Deployment spec (what SHOULD be used):"
kubectl get deployment june-orchestrator -n june-services -o jsonpath='{.spec.template.spec.serviceAccountName}' && echo ""
echo ""

echo "2️⃣ Current running pods:"
kubectl get pods -n june-services -l app=june-orchestrator -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,SA:.spec.serviceAccountName,AGE:.metadata.creationTimestamp
echo ""

echo "3️⃣ ReplicaSet details:"
kubectl get replicaset -n june-services -l app=june-orchestrator -o custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,CURRENT:.status.replicas,READY:.status.readyReplicas,AGE:.metadata.creationTimestamp
echo ""

echo "4️⃣ Deployment events (recent):"
kubectl get events -n june-services --field-selector involvedObject.name=june-orchestrator --sort-by='.lastTimestamp' | tail -10
echo ""

echo "5️⃣ Testing RBAC (if pod exists):"
POD=$(kubectl get pod -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$POD" ]; then
    echo "Testing from pod: $POD"
    SA=$(kubectl get pod -n june-services $POD -o jsonpath='{.spec.serviceAccountName}')
    echo "Pod ServiceAccount: $SA"
    echo ""
    echo "Testing kubectl access to headscale namespace:"
    kubectl exec -n june-services $POD -- kubectl get pods -n headscale 2>&1 | head -10
else
    echo "No pod found!"
fi
