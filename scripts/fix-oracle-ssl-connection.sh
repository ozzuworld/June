#!/bin/bash
# fix-oracle-ssl-connection.sh - Fix Oracle SSL/TLS handshake issues

set -euo pipefail

echo "🔧 Fixing Oracle SSL Connection Issues"

# The errors show SSL handshake problems and socket read timeouts
# This usually means:
# 1. Wrong wallet configuration 
# 2. Incorrect connection string format
# 3. SSL certificate validation issues

echo "Step 1: Check current Oracle connection errors"
kubectl logs deployment/june-idp -n june-services --tail=20 | grep -i "oracle\|ssl\|error" || echo "No recent errors found"

echo "Step 2: Fix Oracle connection configuration"

# Create updated Keycloak configuration with fixed Oracle settings
cat > keycloak-oracle-ssl-fix.yaml << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: keycloak-config
  namespace: june-services
data:
  # FIXED: Use direct connection string instead of TNS alias
  KC_DB: "oracle"
  # Using full connection string with SSL settings
  KC_DB_URL: "jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST=adb.us-ashburn-1.oraclecloud.com)(PORT=1522))(CONNECT_DATA=(SERVICE_NAME=ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com))(SECURITY=(SSL_SERVER_DN_MATCH=YES)))?oracle.net.wallet_location=/opt/oracle/wallet"
  KC_DB_USERNAME: "keycloak_user"
  KC_HOSTNAME_STRICT: "false"
  KC_HTTP_ENABLED: "true"
  KC_HEALTH_ENABLED: "true" 
  KC_METRICS_ENABLED: "true"
  KC_TRANSACTION_XA_ENABLED: "false"
  KC_CACHE: "local"
  KC_LOG_LEVEL: "INFO"
  KC_PROXY: "edge"
  # Oracle SSL environment variables
  TNS_ADMIN: "/opt/oracle/wallet"
  ORACLE_HOME: "/opt/oracle"
  # Disable clustering
  JAVA_OPTS_APPEND: "-XX:MaxRAMPercentage=70.0 -XX:+UseContainerSupport -Dkeycloak.connectionsInfinispan.default.clustered=false -Djgroups.tcp.address=127.0.0.1 -Doracle.net.ssl_server_dn_match=true"

---
# Alternative: Use simplified connection (if wallet approach keeps failing)
apiVersion: v1
kind: ConfigMap
metadata:
  name: keycloak-config-simple
  namespace: june-services
data:
  KC_DB: "oracle"
  # Simplified connection without wallet (less secure but should work)
  KC_DB_URL: "jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=adb.us-ashburn-1.oraclecloud.com)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com)))"
  KC_DB_USERNAME: "keycloak_user"
  KC_HOSTNAME_STRICT: "false"
  KC_HTTP_ENABLED: "true"
  KC_HEALTH_ENABLED: "true"
  KC_METRICS_ENABLED: "true"
  KC_TRANSACTION_XA_ENABLED: "false"
  KC_CACHE: "local"
  KC_LOG_LEVEL: "INFO"
  KC_PROXY: "edge"
  JAVA_OPTS_APPEND: "-XX:MaxRAMPercentage=70.0 -XX:+UseContainerSupport -Dkeycloak.connectionsInfinispan.default.clustered=false"
EOF

echo "✅ Created Oracle SSL fix configuration"

echo "Step 3: Choose fix approach"
echo "Option 1: Try the wallet-based SSL fix (more secure)"
echo "Option 2: Use simplified connection (less secure but should work)"
echo ""
echo "Let's try Option 1 first:"

# Apply the SSL fix
kubectl patch configmap keycloak-config -n june-services --patch-file=/dev/stdin << 'EOF'
data:
  KC_DB_URL: "jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST=adb.us-ashburn-1.oraclecloud.com)(PORT=1522))(CONNECT_DATA=(SERVICE_NAME=ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com))(SECURITY=(SSL_SERVER_DN_MATCH=YES)))?oracle.net.wallet_location=/opt/oracle/wallet"
  JAVA_OPTS_APPEND: "-XX:MaxRAMPercentage=70.0 -XX:+UseContainerSupport -Dkeycloak.connectionsInfinispan.default.clustered=false -Djgroups.tcp.address=127.0.0.1 -Doracle.net.ssl_server_dn_match=true -Doracle.net.ssl_version=1.2"
EOF

echo "✅ Applied Oracle SSL configuration fix"

echo "Step 4: Restart Keycloak deployment"
kubectl rollout restart deployment/june-idp -n june-services

echo "✅ Keycloak deployment restarted"

echo "Step 5: Monitor the fix"
echo "Wait 2-3 minutes for restart, then check logs:"
echo ""
echo "  kubectl logs -f deployment/june-idp -n june-services"
echo ""
echo "Look for:"
echo "  ✅ No more 'ORA-17002: I/O error: Socket read interrupted'"
echo "  ✅ No more SSL handshake errors"
echo "  ✅ 'KC-SERVICES0001: Server is ready for requests'"
echo ""

echo "🔧 If Option 1 still fails, try Option 2:"
echo "  kubectl patch configmap keycloak-config -n june-services --patch='{\"data\":{\"KC_DB_URL\":\"jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=adb.us-ashburn-1.oraclecloud.com)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com)))\"}}}'"
echo "  kubectl rollout restart deployment/june-idp -n june-services"

echo ""
echo "✅ Oracle SSL fix applied - monitor logs for success"