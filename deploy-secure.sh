#!/bin/bash
# deploy-secure.sh - Deploy with proper security

set -euo pipefail

PROJECT_ID="main-buffer-469817-v7"

echo "🔒 Deploying June Platform with enhanced security..."

# Install CSI Secret Store driver (if not already installed)
kubectl apply -f https://raw.githubusercontent.com/kubernetes-sigs/secrets-store-csi-driver/v1.3.0/deploy/secrets-store-csi-driver.yaml

# Install Google Secret Manager provider
kubectl apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/secrets-store-csi-driver-provider-gcp/main/deploy/provider-gcp-plugin.yaml

# Deploy secure secrets configuration
kubectl apply -f k8s/june-services/secure-secrets.yaml

# Deploy secure Keycloak realm
kubectl apply -f k8s/june-services/secure-keycloak-realm.yaml

# Deploy services (update to use secure secrets)
kubectl apply -f k8s/june-services/core-services-no-tts.yaml

echo "✅ Secure deployment completed"
echo ""
echo "🔧 Manual steps required:"
echo "1. Set your external TTS URL:"
echo "   kubectl patch secret june-secrets -n june-services \\"
echo "     --patch='{\"data\":{\"EXTERNAL_TTS_URL\":\"$(echo -n 'https://your-openvoice-service.com' | base64)\"}}"
echo ""
echo "2. Set API keys (if needed):"
echo "   kubectl patch secret june-secrets -n june-services \\"
echo "     --patch='{\"data\":{\"GEMINI_API_KEY\":\"$(echo -n 'your-api-key' | base64)\"}}"
echo ""
echo "3. Update Keycloak client secrets:"
echo "   # Access Keycloak admin console and update client secrets to match Secret Manager values"
echo ""
echo "4. Configure external TTS service to accept June IDP tokens:"
echo "   # Update your OpenVoice service to validate JWT tokens from:"
echo "   # https://june-idp.allsafe.world/auth/realms/june"
