#!/bin/bash
# Debug script for Keycloak connectivity issues

set -e

NAMESPACE="june-services"

echo "=== Keycloak Diagnostic Script ==="
echo ""

echo "1. Checking Keycloak Custom Resource status:"
kubectl get keycloak keycloak -n $NAMESPACE -o yaml
echo ""

echo "2. Checking Keycloak pods:"
kubectl get pods -n $NAMESPACE -l app=keycloak -o wide
echo ""

echo "3. Checking ALL services in namespace:"
kubectl get svc -n $NAMESPACE
echo ""

echo "4. Checking Keycloak-related services (detailed):"
kubectl get svc -n $NAMESPACE -o yaml | grep -A 20 "name: keycloak" || echo "No keycloak services found"
echo ""

echo "5. Checking Ingress resources:"
kubectl get ingress -n $NAMESPACE
echo ""

echo "6. Checking Keycloak ingress details:"
kubectl get ingress -n $NAMESPACE -o yaml | grep -A 30 "keycloak" || echo "No keycloak ingress found"
echo ""

echo "7. Testing direct pod connectivity:"
POD_NAME=$(kubectl get pods -n $NAMESPACE -l app=keycloak -o jsonpath='{.items[0].metadata.name}')
if [ -n "$POD_NAME" ]; then
    echo "Pod: $POD_NAME"
    echo "Testing HTTP port 8080:"
    kubectl exec -n $NAMESPACE $POD_NAME -- curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health || echo "Failed"
    echo ""
    echo "Testing HTTP port 8443:"
    kubectl exec -n $NAMESPACE $POD_NAME -- curl -k -s -o /dev/null -w "%{http_code}" https://localhost:8443/health || echo "Failed"
    echo ""
else
    echo "No Keycloak pod found"
fi

echo "8. Checking for any Keycloak service endpoints:"
kubectl get endpoints -n $NAMESPACE | grep keycloak || echo "No keycloak endpoints found"
echo ""

echo "9. Describe Keycloak CR (looking for status/errors):"
kubectl describe keycloak keycloak -n $NAMESPACE | tail -30
echo ""

echo "=== Diagnostic Complete ==="
