#!/bin/bash
# quick-wallet-fix.sh - Fix wallet directory and file issues

set -euo pipefail

echo "🔧 Quick Wallet Fix"

# Step 1: Go to project root
echo "Step 1: Moving to project root"
cd ../../../  # Go up from keycloakdb_wallet to project root
pwd
echo "✅ Now in project root"

# Step 2: Verify wallet files exist and are readable
echo "Step 2: Checking wallet files"
WALLET_DIR="k8s/june-services/keycloakdb_wallet"

if [[ ! -d "$WALLET_DIR" ]]; then
    echo "❌ Wallet directory still not found: $WALLET_DIR"
    echo "Current directory: $(pwd)"
    echo "Available directories:"
    find . -name "keycloakdb_wallet" -type d
    exit 1
fi

echo "✅ Wallet directory found: $WALLET_DIR"

# Check individual files
REQUIRED_FILES=("cwallet.sso" "ewallet.p12" "tnsnames.ora" "sqlnet.ora")
for file in "${REQUIRED_FILES[@]}"; do
    if [[ -f "$WALLET_DIR/$file" ]]; then
        echo "✅ Found: $file ($(stat -c%s "$WALLET_DIR/$file" 2>/dev/null || stat -f%z "$WALLET_DIR/$file" 2>/dev/null || echo "unknown size") bytes)"
    else
        echo "❌ Missing: $file"
    fi
done

# Step 3: Check file permissions and fix if needed
echo "Step 3: Checking file permissions"
ls -la "$WALLET_DIR/"

# Fix permissions if needed (sometimes wallet files have wrong permissions)
echo "Step 4: Fixing file permissions"
chmod 644 "$WALLET_DIR"/* 2>/dev/null || echo "Could not change permissions (may not be needed)"

echo "✅ Wallet files verified and permissions fixed"

# Step 5: Create wallet secret manually (faster approach)
echo "Step 5: Creating Oracle wallet secret directly"

kubectl delete secret oracle-wallet -n june-services --ignore-not-found=true

kubectl create secret generic oracle-wallet -n june-services \
    --from-file=cwallet.sso="$WALLET_DIR/cwallet.sso" \
    --from-file=ewallet.p12="$WALLET_DIR/ewallet.p12" \
    --from-file=tnsnames.ora="$WALLET_DIR/tnsnames.ora" \
    --from-file=sqlnet.ora="$WALLET_DIR/sqlnet.ora"

echo "✅ Oracle wallet secret created successfully"

# Step 6: Create other required secrets
echo "Step 6: Creating Oracle credentials and Keycloak admin secrets"

kubectl delete secret oracle-credentials -n june-services --ignore-not-found=true
kubectl create secret generic oracle-credentials -n june-services \
    --from-literal=DB_HOST="adb.us-ashburn-1.oraclecloud.com" \
    --from-literal=DB_PORT="1522" \
    --from-literal=DB_SERVICE="ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com" \
    --from-literal=DB_USER="keycloak_user" \
    --from-literal=DB_PASSWORD="KeycloakPass123!@#"

kubectl delete secret keycloak-admin -n june-services --ignore-not-found=true
kubectl create secret generic keycloak-admin -n june-services \
    --from-literal=KEYCLOAK_ADMIN="admin" \
    --from-literal=KEYCLOAK_ADMIN_PASSWORD="admin123456"

echo "✅ All secrets created successfully"

# Step 7: Verify secrets were created
echo "Step 7: Verifying secrets"
kubectl get secrets -n june-services | grep -E "(oracle-wallet|oracle-credentials|keycloak-admin)"

echo ""
echo "🎉 Wallet setup completed successfully!"
echo ""
echo "Next steps:"
echo "1. Now run the Keycloak deployment:"
echo "   kubectl apply -f k8s/june-services/keycloak-oracle-fixed.yaml"
echo "2. Or use the full IDP deployment script from project root:"
echo "   ./deploy-idp-step-by-step.sh"