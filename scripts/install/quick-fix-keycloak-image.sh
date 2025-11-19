#!/bin/bash
set -e

echo "============================================"
echo "Quick Fix: Switch to Quay.io Keycloak Image"
echo "============================================"
echo ""
echo "This replaces Docker Hub image with Quay.io (no rate limiting)"
echo ""

NAMESPACE="june-services"

# Update the deployment to use official Quay.io image
kubectl set image deployment/june-idp \
  keycloak=quay.io/keycloak/keycloak:26.0.4 \
  -n $NAMESPACE

echo ""
echo "✅ Image updated to quay.io/keycloak/keycloak:26.0.4"
echo ""
echo "Monitoring rollout..."
kubectl rollout status deployment/june-idp -n $NAMESPACE --timeout=5m

echo ""
echo "✅ Quick fix applied successfully!"
echo ""
echo "Keycloak is now using the official image from Quay.io (no Docker Hub rate limits)"
echo ""
echo "Check pods:"
echo "  kubectl get pods -n $NAMESPACE -l app=june-idp"
