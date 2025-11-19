#!/bin/bash
set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

NAMESPACE="june-services"
KEYCLOAK_RELEASE_NAME="keycloak"
VALUES_FILE="${ROOT_DIR}/helm/keycloak-values.yaml"

echo "============================================"
echo "Migrating to Bitnami Keycloak Helm Chart"
echo "============================================"
echo ""
echo -e "${BLUE}This will migrate from custom june-idp to official Bitnami Keycloak chart${NC}"
echo ""

# Verify prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

if ! command -v helm &> /dev/null; then
    echo -e "${RED}✗ Helm not found. Please install Helm first.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Helm found: $(helm version --short)${NC}"

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}✗ kubectl not found. Please install kubectl first.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ kubectl found${NC}"

# Check if namespace exists
if ! kubectl get namespace $NAMESPACE &> /dev/null; then
    echo -e "${RED}✗ Namespace '$NAMESPACE' not found${NC}"
    echo "Create it first with: kubectl create namespace $NAMESPACE"
    exit 1
fi
echo -e "${GREEN}✓ Namespace '$NAMESPACE' exists${NC}"

# Check if values file exists
if [ ! -f "$VALUES_FILE" ]; then
    echo -e "${RED}✗ Values file not found: $VALUES_FILE${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Values file found: $VALUES_FILE${NC}"
echo ""

# Step 1: Add/Update Bitnami repository
echo -e "${YELLOW}Step 1: Add Bitnami Helm repository${NC}"
helm repo add bitnami https://charts.bitnami.com/bitnami 2>/dev/null || echo "Bitnami repo already exists"
helm repo update
echo -e "${GREEN}✓ Bitnami repository updated${NC}"
echo ""

# Step 2: Check for existing Keycloak data
echo -e "${YELLOW}Step 2: Check for existing Keycloak deployment${NC}"

OLD_IDP_EXISTS=false
OLD_POSTGRES_EXISTS=false

if kubectl get deployment june-idp -n $NAMESPACE &> /dev/null; then
    OLD_IDP_EXISTS=true
    echo -e "${BLUE}Found existing june-idp deployment${NC}"
fi

if kubectl get statefulset postgresql -n $NAMESPACE &> /dev/null; then
    OLD_POSTGRES_EXISTS=true
    echo -e "${BLUE}Found existing PostgreSQL statefulset${NC}"
fi

if [ "$OLD_IDP_EXISTS" = true ] || [ "$OLD_POSTGRES_EXISTS" = true ]; then
    echo ""
    echo -e "${RED}WARNING: Existing Keycloak deployment detected!${NC}"
    echo ""
    echo "Migration options:"
    echo "  1) Fresh install (DELETES all existing Keycloak data - realms, users, etc.)"
    echo "  2) Data migration (keeps PostgreSQL data - RECOMMENDED if you have users/realms)"
    echo "  3) Cancel (abort migration)"
    echo ""
    read -p "Choose option (1/2/3): " MIGRATION_OPTION

    case $MIGRATION_OPTION in
        1)
            echo -e "${YELLOW}You chose: Fresh install${NC}"
            echo -e "${RED}This will DELETE all Keycloak data!${NC}"
            read -p "Type 'DELETE' to confirm: " CONFIRM
            if [ "$CONFIRM" != "DELETE" ]; then
                echo "Migration cancelled"
                exit 0
            fi
            MIGRATE_DATA=false
            ;;
        2)
            echo -e "${YELLOW}You chose: Data migration${NC}"
            MIGRATE_DATA=true
            ;;
        3)
            echo "Migration cancelled"
            exit 0
            ;;
        *)
            echo "Invalid option"
            exit 1
            ;;
    esac
else
    echo -e "${GREEN}No existing Keycloak deployment found - clean install${NC}"
    MIGRATE_DATA=false
fi
echo ""

# Step 3: Data migration (if needed)
if [ "$MIGRATE_DATA" = true ]; then
    echo -e "${YELLOW}Step 3: Migrate PostgreSQL data${NC}"
    echo ""
    echo "Creating PostgreSQL backup..."

    # Create backup of PostgreSQL data
    BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
    BACKUP_NAME="keycloak-db-backup-${BACKUP_DATE}"

    kubectl exec -n $NAMESPACE postgresql-0 -- bash -c \
        "PGPASSWORD=Pokemon123! pg_dump -U keycloak -d keycloak" > "/tmp/${BACKUP_NAME}.sql"

    echo -e "${GREEN}✓ Database backed up to: /tmp/${BACKUP_NAME}.sql${NC}"
    echo ""

    # Remove old deployments but keep data
    echo "Removing old june-idp deployment (keeping data)..."
    kubectl delete deployment june-idp -n $NAMESPACE --ignore-not-found=true

    echo ""
    echo -e "${BLUE}Note: We'll restore data after installing Bitnami Keycloak${NC}"
else
    # Step 3: Clean removal
    echo -e "${YELLOW}Step 3: Remove old Keycloak deployment${NC}"

    if [ "$OLD_IDP_EXISTS" = true ]; then
        echo "Removing june-idp deployment..."
        kubectl delete deployment june-idp -n $NAMESPACE --ignore-not-found=true
    fi

    if [ "$OLD_POSTGRES_EXISTS" = true ]; then
        echo "Removing PostgreSQL statefulset..."
        kubectl delete statefulset postgresql -n $NAMESPACE --ignore-not-found=true
        kubectl delete pvc postgresql-pvc -n $NAMESPACE --ignore-not-found=true
        kubectl delete pv postgresql-pv --ignore-not-found=true
        kubectl delete service postgresql -n $NAMESPACE --ignore-not-found=true
    fi

    echo -e "${GREEN}✓ Old deployment removed${NC}"
fi
echo ""

# Step 4: Install Bitnami Keycloak
echo -e "${YELLOW}Step 4: Install Bitnami Keycloak${NC}"

# Check if already installed
if helm list -n $NAMESPACE | grep -q "^$KEYCLOAK_RELEASE_NAME"; then
    echo "Keycloak already installed. Upgrading..."
    helm upgrade $KEYCLOAK_RELEASE_NAME bitnami/keycloak \
        --namespace $NAMESPACE \
        --values "$VALUES_FILE" \
        --wait \
        --timeout 10m
else
    echo "Installing Keycloak..."
    helm install $KEYCLOAK_RELEASE_NAME bitnami/keycloak \
        --namespace $NAMESPACE \
        --values "$VALUES_FILE" \
        --wait \
        --timeout 10m
fi

echo -e "${GREEN}✓ Bitnami Keycloak installed${NC}"
echo ""

# Step 5: Restore data (if migrated)
if [ "$MIGRATE_DATA" = true ]; then
    echo -e "${YELLOW}Step 5: Restore PostgreSQL data${NC}"

    # Wait for PostgreSQL to be ready
    echo "Waiting for PostgreSQL to be ready..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=postgresql -n $NAMESPACE --timeout=300s

    # Get the new PostgreSQL pod name
    POSTGRES_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=postgresql -o jsonpath='{.items[0].metadata.name}')

    # Restore the database
    echo "Restoring database backup..."
    cat "/tmp/${BACKUP_NAME}.sql" | kubectl exec -i -n $NAMESPACE $POSTGRES_POD -- \
        bash -c "PGPASSWORD=Pokemon123! psql -U keycloak -d keycloak"

    echo -e "${GREEN}✓ Database restored successfully${NC}"

    # Restart Keycloak to pick up the data
    echo "Restarting Keycloak pods..."
    kubectl rollout restart deployment -l app.kubernetes.io/name=keycloak -n $NAMESPACE
    kubectl rollout status deployment -l app.kubernetes.io/name=keycloak -n $NAMESPACE --timeout=5m

    echo -e "${GREEN}✓ Data migration complete${NC}"
fi
echo ""

# Step 6: Verify installation
echo -e "${YELLOW}Step 6: Verify installation${NC}"

# Check pods
KEYCLOAK_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=keycloak -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [ -z "$KEYCLOAK_POD" ]; then
    echo -e "${RED}✗ Keycloak pod not found${NC}"
    echo "Check status with: kubectl get pods -n $NAMESPACE"
    exit 1
fi

POD_STATUS=$(kubectl get pod $KEYCLOAK_POD -n $NAMESPACE -o jsonpath='{.status.phase}')
if [ "$POD_STATUS" != "Running" ]; then
    echo -e "${RED}✗ Keycloak pod not running (status: $POD_STATUS)${NC}"
    echo "Check logs with: kubectl logs -n $NAMESPACE $KEYCLOAK_POD"
    exit 1
fi

echo -e "${GREEN}✓ Keycloak pod is running${NC}"

# Check readiness
READY=$(kubectl get pod $KEYCLOAK_POD -n $NAMESPACE -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
if [ "$READY" = "True" ]; then
    echo -e "${GREEN}✓ Keycloak pod is ready${NC}"
else
    echo -e "${YELLOW}⚠ Keycloak pod not ready yet (may still be starting)${NC}"
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}✅ Migration complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Keycloak is now running using the official Bitnami Helm chart."
echo ""
echo -e "${BLUE}Access Information:${NC}"
echo "  URL: https://idp.ozzu.world"
echo "  Admin user: admin"
echo "  Admin password: Pokemon123! (CHANGE THIS IN PRODUCTION)"
echo ""
echo -e "${BLUE}Useful Commands:${NC}"
echo "  Check pods:"
echo "    kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=keycloak"
echo ""
echo "  View logs:"
echo "    kubectl logs -n $NAMESPACE -l app.kubernetes.io/name=keycloak -f"
echo ""
echo "  Update configuration:"
echo "    helm upgrade $KEYCLOAK_RELEASE_NAME bitnami/keycloak \\"
echo "      --namespace $NAMESPACE \\"
echo "      --values $VALUES_FILE"
echo ""
echo "  Check Helm release:"
echo "    helm list -n $NAMESPACE"
echo ""
echo "  Uninstall (if needed):"
echo "    helm uninstall $KEYCLOAK_RELEASE_NAME -n $NAMESPACE"
echo ""

if [ "$MIGRATE_DATA" = true ]; then
    echo -e "${YELLOW}Note: Database backup saved to /tmp/${BACKUP_NAME}.sql${NC}"
    echo "Keep this file safe until you verify the migration was successful."
    echo ""
fi

echo -e "${BLUE}Next Steps:${NC}"
echo "1. Access https://idp.ozzu.world and verify you can log in"
echo "2. Check that your realms and users are present (if migrated)"
echo "3. Update any applications that connect to Keycloak (service name changed)"
echo "4. Change the admin password in production!"
echo ""
