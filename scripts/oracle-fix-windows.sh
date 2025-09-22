#!/bin/bash
# oracle-fix-windows.sh - Oracle SSL fix that works on Windows

set -euo pipefail

echo "🔧 Oracle SSL Fix (Windows Compatible)"

# Step 1: Create a temporary patch file
echo "Step 1: Creating Oracle connection fix"

cat > oracle-connection-fix.yaml << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: keycloak-config
  namespace: june-services
data:
  KC_DB: "oracle"
  KC_DB_URL: "jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST=adb.us-ashburn-1.oraclecloud.com)(PORT=1522))(CONNECT_DATA=(SERVICE_NAME=ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com))(SECURITY=(SSL_SERVER_DN_MATCH=YES)))?oracle.net.wallet_location=/opt/oracle/wallet&oracle.net.ssl_version=1.2"
  KC_DB_USERNAME: "keycloak_user"
  KC_HOSTNAME_STRICT: "false"
  KC_HTTP_ENABLED: "true"
  KC_HEALTH_ENABLED: "true"
  KC_METRICS_ENABLED: "true"
  KC_TRANSACTION_XA_ENABLED: "false"
  KC_CACHE: "local"
  KC_LOG_LEVEL: "INFO"
  KC_PROXY: "edge"
  TNS_ADMIN: "/opt/oracle/wallet"
  ORACLE_HOME: "/opt/oracle"
  JAVA_OPTS_APPEND: "-XX:MaxRAMPercentage=70.0 -XX:+UseContainerSupport -Dkeycloak.connectionsInfinispan.default.clustered=false -Djgroups.tcp.address=127.0.0.1 -Doracle.net.ssl_server_dn_match=true -Doracle.net.ssl_version=1.2 -Doracle.net.CONNECT_TIMEOUT=60000 -Doracle.jdbc.ReadTimeout=60000"
EOF

echo "✅ Oracle fix configuration created"

# Step 2: Apply the fix
echo "Step 2: Applying Oracle SSL connection fix"
kubectl apply -f oracle-connection-fix.yaml

echo "✅ Oracle configuration updated"

# Step 3: Restart deployment
echo "Step 3: Restarting Keycloak deployment"
kubectl rollout restart deployment/june-idp -n june-services

echo "✅ Deployment restarted"

# Step 4: Wait and monitor
echo "Step 4: Waiting for restart (30 seconds)..."
sleep 30

# Get pod name
POD_NAME=$(kubectl get pods -n june-services -l app=june-idp -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [[ -n "$POD_NAME" ]]; then
    echo "📋 New pod: $POD_NAME"
    echo ""
    echo "🔍 Monitoring Oracle connection (press Ctrl+C to stop)..."
    echo "Looking for success indicators:"
    echo "  ✅ No more 'ORA-17002' errors"
    echo "  ✅ Database schema creation messages"
    echo "  ✅ 'KC-SERVICES0001: Server is ready'"
    echo ""
    
    # Monitor logs for 60 seconds
    timeout 60s kubectl logs -f $POD_NAME -n june-services 2>/dev/null || echo "Monitoring timeout - check manually with: kubectl logs -f deployment/june-idp -n june-services"
else
    echo "⚠️ Pod not found yet. Check with: kubectl get pods -n june-services"
fi

echo ""
echo "🔧 If Oracle still fails after 10 minutes, try PostgreSQL alternative:"
echo "   ./postgresql-alternative.sh"
echo ""
echo "💡 PostgreSQL is much more reliable for development (2-5 min vs 15-30 min)"

# Clean up
rm -f oracle-connection-fix.yaml