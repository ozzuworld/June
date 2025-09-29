#!/bin/bash
# diagnose-and-fix-june-idp.sh

echo "🔍 DIAGNOSING JUNE-IDP DATABASE CONNECTION"
echo "=========================================="

# Check current june-idp deployment
echo "1️⃣ Current june-idp deployment configuration:"
kubectl get deployment june-idp -n june-services -o yaml | grep -A 20 "env:" | grep -E "(KC_DB|POSTGRES|DATABASE)"

echo ""
echo "2️⃣ Current database services in june-services namespace:"
kubectl get services -n june-services | grep -E "(postgres|db)"

echo ""
echo "3️⃣ Current database secrets:"
kubectl get secrets -n june-services | grep -E "(postgres|db|keycloak)"

echo ""
echo "4️⃣ Checking keycloak-db status:"
kubectl get pods -n june-services | grep keycloak-db
kubectl get service keycloak-db -n june-services

echo ""
echo "5️⃣ Current june-idp pod status and logs:"
JUNE_IDP_POD=$(kubectl get pods -n june-services -l app=june-idp -o jsonpath='{.items[0].metadata.name}')
if [ ! -z "$JUNE_IDP_POD" ]; then
    echo "Pod: $JUNE_IDP_POD"
    kubectl logs -n june-services $JUNE_IDP_POD --tail=50 | grep -i -E "(database|postgres|connection|error)"
fi