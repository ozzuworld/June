#!/bin/bash
# fix-keycloak-jvm.sh - Fix the JVM garbage collector conflict

set -euo pipefail

echo "🔧 Fixing Keycloak JVM Configuration Issue"
echo "=========================================="

# The error shows: "Multiple garbage collectors selected"
# This happens when we specify -XX:+UseG1GC but Keycloak already has default GC settings

echo "📋 Current error: Multiple garbage collectors selected"
echo "🔧 Solution: Remove conflicting JVM options"

# Step 1: Fix the ConfigMap with simpler JVM settings
echo ""
echo "Step 1: Updating Keycloak configuration with fixed JVM settings"

# Create a patch with corrected JVM options
cat > keycloak-jvm-fix.yaml << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: keycloak-postgres-config
  namespace: june-services
data:
  KC_DB: "postgres"
  KC_DB_URL: "jdbc:postgresql://postgresql:5432/keycloak"
  KC_DB_USERNAME: "keycloak"
  KC_DB_SCHEMA: "public"
  KC_DB_POOL_INITIAL_SIZE: "5"
  KC_DB_POOL_MIN_SIZE: "5"
  KC_DB_POOL_MAX_SIZE: "20"
  KC_HOSTNAME_STRICT: "false"
  KC_HTTP_ENABLED: "true"
  KC_HEALTH_ENABLED: "true"
  KC_METRICS_ENABLED: "true"
  KC_TRANSACTION_XA_ENABLED: "false"
  KC_CACHE: "local"
  KC_LOG_LEVEL: "INFO"
  KC_PROXY: "edge"
  # FIXED: Simplified JVM settings without conflicting garbage collectors
  JAVA_OPTS_APPEND: "-XX:MaxRAMPercentage=70.0 -XX:+UseContainerSupport -Dkeycloak.connectionsInfinispan.default.clustered=false"
EOF

echo "✅ Created fixed configuration (removed conflicting G1GC settings)"

# Apply the fix
kubectl apply -f keycloak-jvm-fix.yaml

echo "✅ Applied fixed configuration"

# Step 2: Restart the deployment to pick up the changes
echo ""
echo "Step 2: Restarting Keycloak deployment with fixed settings"
kubectl rollout restart deployment/june-idp-postgres -n june-services

echo "✅ Keycloak deployment restarted"

# Step 3: Monitor the fix
echo ""
echo "Step 3: Monitoring Keycloak startup (this should work now)"
echo "⏳ Waiting 30 seconds for restart..."
sleep 30

# Check pod status
POD_NAME=$(kubectl get pods -n june-services -l app=june-idp-postgres -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [[ -n "$POD_NAME" ]]; then
    echo "📋 New pod: $POD_NAME"
    
    # Check if the JVM error is gone
    echo ""
    echo "🔍 Checking for JVM errors (should be none now):"
    kubectl logs $POD_NAME -n june-services 2>/dev/null | grep -E "(Multiple garbage collectors|Error occurred during initialization)" || echo "✅ No JVM errors found!"
    
    echo ""
    echo "📊 Current pod status:"
    kubectl get pods -n june-services | grep postgres
    
    echo ""
    echo "⏳ Monitoring startup progress for 60 seconds..."
    echo "Looking for:"
    echo "  ✅ No 'Multiple garbage collectors' errors"
    echo "  ✅ 'Changes detected in configuration. Updating the server image.'"
    echo "  ✅ 'KC-SERVICES0009: Added user admin to realm master'"
    echo "  ✅ 'KC-SERVICES0001: Server is ready for requests'"
    echo ""
    
    # Monitor logs for 60 seconds
    timeout 60s kubectl logs -f $POD_NAME -n june-services 2>/dev/null | grep -E "(ready|started|error|ERROR|WARN|KC-SERVICES)" || echo "Monitoring timeout"
    
else
    echo "⚠️ Pod not found yet. Check with: kubectl get pods -n june-services"
fi

# Clean up
rm -f keycloak-jvm-fix.yaml

echo ""
echo "🎯 What we fixed:"
echo "=================="
echo "❌ BEFORE: JAVA_OPTS_APPEND with -XX:+UseG1GC (conflicted with default GC)"
echo "✅ AFTER:  JAVA_OPTS_APPEND without G1GC (uses Keycloak default GC)"
echo ""
echo "📊 Expected result:"
echo "  - No more 'Multiple garbage collectors selected' errors"
echo "  - Keycloak starts successfully"
echo "  - Pod status changes from CrashLoopBackOff to Running"
echo ""
echo "🔧 If still not working after 5 minutes, check:"
echo "  kubectl logs -f deployment/june-idp-postgres -n june-services"
echo "  kubectl describe pod $POD_NAME -n june-services"