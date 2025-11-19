#!/bin/bash
set -e

echo "============================================"
echo "Migrating to Bitnami Keycloak Helm Chart"
echo "============================================"

NAMESPACE="june-services"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${YELLOW}Step 1: Add Bitnami Helm repository${NC}"
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

echo ""
echo -e "${YELLOW}Step 2: Backup current Keycloak data (if needed)${NC}"
echo "If you have important realm/user data, back it up now."
echo "Press Enter to continue or Ctrl+C to abort..."
read

echo ""
echo -e "${YELLOW}Step 3: Remove old june-idp deployment${NC}"
kubectl delete deployment june-idp -n $NAMESPACE --ignore-not-found=true

echo ""
echo -e "${YELLOW}Step 4: Install Bitnami Keycloak${NC}"
helm install keycloak bitnami/keycloak \
  --namespace $NAMESPACE \
  --values /home/user/June/helm/keycloak-values.yaml \
  --wait \
  --timeout 10m

echo ""
echo -e "${GREEN}✅ Migration complete!${NC}"
echo ""
echo "Keycloak is now running using the official Bitnami Helm chart."
echo ""
echo "Access Keycloak:"
echo "  URL: https://idp.ozzu.world"
echo "  Admin user: admin"
echo "  Admin password: Pokemon123! (CHANGE THIS IN PRODUCTION)"
echo ""
echo "Check status:"
echo "  kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=keycloak"
echo ""
echo "View logs:"
echo "  kubectl logs -n $NAMESPACE -l app.kubernetes.io/name=keycloak -f"
echo ""
echo "Update values:"
echo "  helm upgrade keycloak bitnami/keycloak \\"
echo "    --namespace $NAMESPACE \\"
echo "    --values /home/user/June/helm/keycloak-values.yaml"
