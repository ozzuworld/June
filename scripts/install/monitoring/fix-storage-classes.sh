#!/bin/bash
set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "============================================"
echo "Monitoring Stack - Storage Class Fix"
echo "============================================"
echo ""

# Step 1: Check available storage classes
echo -e "${YELLOW}Step 1: Checking available storage classes...${NC}"
echo ""
kubectl get storageclasses

echo ""
echo -e "${BLUE}Current monitoring PVC status:${NC}"
kubectl get pvc -n monitoring 2>/dev/null || echo "No PVCs yet"

echo ""
echo ""
echo -e "${YELLOW}Storage class fix options:${NC}"
echo ""
echo "Option 1: Use 'standard' storage class (typical for most clusters)"
echo "Option 2: Create custom 'fast-ssd' and 'slow-hdd' storage classes"
echo "Option 3: Manually specify your storage class"
echo ""
read -p "Choose option (1/2/3): " OPTION

case $OPTION in
    1)
        echo -e "${YELLOW}Using 'standard' storage class...${NC}"
        STORAGE_CLASS="standard"
        ;;
    2)
        echo -e "${YELLOW}Creating custom storage classes...${NC}"

        # Check if using local-path provisioner (common in single-node/dev clusters)
        if kubectl get storageclass | grep -q "local-path"; then
            echo "Detected local-path provisioner. Creating storage classes..."

            # Create fast-ssd storage class
            cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
EOF

            # Create slow-hdd storage class
            cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: slow-hdd
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
EOF

            echo -e "${GREEN}✓ Storage classes created${NC}"
            kubectl get storageclass fast-ssd slow-hdd

            # Restart the installation
            echo ""
            echo -e "${BLUE}Now restart the monitoring installation:${NC}"
            echo "  cd /home/kazuma.ozzu/June/scripts/install/monitoring"
            echo "  bash install-observability-stack.sh"
            exit 0
        else
            echo -e "${RED}Unknown storage provisioner${NC}"
            echo "Please manually create 'fast-ssd' and 'slow-hdd' storage classes"
            echo "Or choose option 3 to specify your storage class"
            exit 1
        fi
        ;;
    3)
        echo ""
        read -p "Enter your storage class name: " STORAGE_CLASS
        echo -e "${YELLOW}Using storage class: $STORAGE_CLASS${NC}"
        ;;
    *)
        echo -e "${RED}Invalid option${NC}"
        exit 1
        ;;
esac

# Update the values file
echo ""
echo -e "${YELLOW}Step 2: Updating values.yaml with storage class: $STORAGE_CLASS${NC}"

VALUES_FILE="/home/kazuma.ozzu/June/k8s/monitoring/prometheus/values.yaml"

# Backup original
cp "$VALUES_FILE" "${VALUES_FILE}.backup-$(date +%Y%m%d_%H%M%S)"

# Replace storage classes
sed -i "s/storageClassName: slow-hdd/storageClassName: $STORAGE_CLASS/g" "$VALUES_FILE"
sed -i "s/storageClassName: fast-ssd/storageClassName: $STORAGE_CLASS/g" "$VALUES_FILE"

echo -e "${GREEN}✓ Values file updated${NC}"

# Step 3: Reinstall
echo ""
echo -e "${YELLOW}Step 3: Removing failed installation...${NC}"

# Delete the release
helm uninstall kube-prometheus-stack -n monitoring 2>/dev/null || echo "Release not found (continuing)"

# Delete stuck PVCs
kubectl delete pvc -n monitoring --all --wait=false 2>/dev/null || echo "No PVCs to delete"

# Wait a moment
sleep 5

echo -e "${GREEN}✓ Cleanup complete${NC}"

# Step 4: Reinstall
echo ""
echo -e "${YELLOW}Step 4: Reinstalling with correct storage class...${NC}"
echo ""

cd /home/kazuma.ozzu/June/scripts/install/monitoring
bash install-observability-stack.sh

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}✅ Storage class fix complete!${NC}"
echo -e "${GREEN}============================================${NC}"
