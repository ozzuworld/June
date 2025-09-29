#!/bin/bash
# Complete fix script for june-idp keycloak connection

echo "🔧 FIXING JUNE-IDP KEYCLOAK CONNECTION"
echo "======================================"

# Step 1: Delete the broken deployment
echo "1️⃣ Removing broken june-idp deployment..."
kubectl delete deployment june-idp -n june-services --ignore-not-found=true

# Step 2: Remove any wrong keycloak-postgres service/deployment if it exists
echo "2️⃣ Cleaning up wrong keycloak-postgres resources..."
kubectl delete deployment keycloak-postgres -n june-services --ignore-not-found=true
kubectl delete service keycloak-postgres -n june-services --ignore-not-found=true

# Step 3: Apply the corrected configuration
echo "3️⃣ Applying corrected june-idp configuration..."
kubectl apply -f infrastructure/kubernetes/june-idp-keycloak-fixed.yaml

# Step 4: Wait for deployment to be ready
echo "4️⃣ Waiting for june-idp to be ready..."
kubectl wait --for=condition=available --timeout=300s deployment/june-idp -n june-services

# Step 5: Check the status
echo "5️⃣ Checking deployment status..."
kubectl get deployments -n june-services | grep -E "(keycloak-db|june-idp)"
kubectl get pods -n june-services | grep -E "(keycloak-db|june-idp)"

# Step 6: Check logs for any issues
echo "6️⃣ Checking june-idp logs (last 20 lines)..."
kubectl logs -n june-services deployment/june-idp --tail=20

echo ""
echo "✅ DEPLOYMENT COMPLETE!"
echo "Check the status above. If june-idp shows 1/1 Ready, it's working!"
echo ""
echo "🌐 To access Keycloak admin:"
echo "kubectl port-forward -n june-services svc/june-idp 8080:8080"
echo "Then visit: http://localhost:8080"
echo "Admin credentials: admin / (check keycloak-admin-secret)"