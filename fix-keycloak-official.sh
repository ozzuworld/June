#!/bin/bash
# fix-keycloak-official.sh - Fix using official Keycloak Kubernetes documentation

set -euo pipefail

echo "🔧 Fixing Keycloak Configuration Using Official Documentation"
echo "=========================================================="
echo ""
echo "📋 Current issue: '--db' not usable with pre-built image and --optimized"
echo "🔗 Following: https://www.keycloak.org/getting-started/getting-started-kube"
echo ""

# The official Keycloak documentation shows we should either:
# 1. Use environment variables only (recommended)
# 2. OR use --db without --optimized
# 3. OR build custom image

echo "🔧 Solution: Use environment variables instead of command line arguments"

# Step 1: Create corrected Keycloak deployment
echo "Step 1: Creating Keycloak deployment following official guide"

cat > keycloak-official-fix.yaml << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-idp-postgres
  namespace: june-services
  labels:
    app: june-idp-postgres
spec:
  replicas: 1
  selector:
    matchLabels:
      app: june-idp-postgres
  template:
    metadata:
      labels:
        app: june-idp-postgres
    spec:
      initContainers:
      - name: wait-for-postgres
        image: postgres:15-alpine
        command: ['sh', '-c']
        args:
          - |
            echo "🐘 Waiting for PostgreSQL to be ready..."
            until pg_isready -h postgresql -p 5432 -U keycloak -d keycloak; do
              echo "PostgreSQL not ready, waiting 5 seconds..."
              sleep 5
            done
            echo "✅ PostgreSQL is ready!"
            echo "📊 PostgreSQL connection test:"
            PGPASSWORD=keycloak_secure_password_123 psql -h postgresql -U keycloak -d keycloak -c "SELECT version();" || echo "Connection test failed but continuing..."
        resources:
          requests:
            memory: "64Mi"
            cpu: "50m"
          limits:
            memory: "128Mi"
            cpu: "100m"
      
      containers:
      - name: keycloak
        image: quay.io/keycloak/keycloak:23.0.0
        # FIXED: Use simple start command following official documentation
        args:
          - "start-dev"
          - "--http-enabled=true"
          - "--hostname-strict=false"
        
        ports:
        - name: http
          containerPort: 8080
        
        # FIXED: Use environment variables for all database configuration
        env:
        - name: KC_DB
          value: "postgres"
        - name: KC_DB_URL
          value: "jdbc:postgresql://postgresql:5432/keycloak"
        - name: KC_DB_USERNAME
          value: "keycloak"
        - name: KC_DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: keycloak-postgres-secrets
              key: KC_DB_PASSWORD
        - name: KC_DB_SCHEMA
          value: "public"
        
        # Keycloak admin configuration
        - name: KEYCLOAK_ADMIN
          valueFrom:
            secretKeyRef:
              name: keycloak-postgres-secrets
              key: KEYCLOAK_ADMIN
        - name: KEYCLOAK_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: keycloak-postgres-secrets
              key: KEYCLOAK_ADMIN_PASSWORD
        
        # Additional configuration
        - name: KC_HOSTNAME_STRICT
          value: "false"
        - name: KC_HTTP_ENABLED
          value: "true"
        - name: KC_HEALTH_ENABLED
          value: "true"
        - name: KC_METRICS_ENABLED
          value: "true"
        
        # FIXED: Simplified JVM options (no conflicting settings)
        - name: JAVA_OPTS_APPEND
          value: "-XX:MaxRAMPercentage=70.0 -XX:+UseContainerSupport"
        
        resources:
          requests:
            memory: "512Mi"
            cpu: "200m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        
        # Health checks with appropriate timeouts
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 120
          periodSeconds: 30
          timeoutSeconds: 10
          failureThreshold: 5
        
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 60
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 10
        
        startupProbe:
          httpGet:
            path: /health/started
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 15
          timeoutSeconds: 10
          failureThreshold: 20
EOF

echo "✅ Created Keycloak configuration following official documentation"

# Step 2: Apply the corrected configuration
echo ""
echo "Step 2: Applying official Keycloak configuration"
kubectl apply -f keycloak-official-fix.yaml

echo "✅ Applied corrected Keycloak deployment"

# Step 3: Wait and monitor
echo ""
echo "Step 3: Monitoring Keycloak startup with corrected configuration"
echo "⏳ Waiting 30 seconds for deployment to start..."
sleep 30

# Get pod status
kubectl get pods -n june-services | grep postgres

echo ""
echo "📋 Checking for the previous errors (should be gone now):"

POD_NAME=$(kubectl get pods -n june-services -l app=june-idp-postgres -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [[ -n "$POD_NAME" ]]; then
    echo "Pod: $POD_NAME"
    
    # Check for the specific errors we're fixing
    echo ""
    echo "🔍 Checking for fixed issues:"
    
    # Check for JVM errors (should be none)
    if kubectl logs $POD_NAME -n june-services 2>/dev/null | grep -q "Multiple garbage collectors"; then
        echo "❌ Still has JVM garbage collector errors"
    else
        echo "✅ No JVM garbage collector errors"
    fi
    
    # Check for Keycloak build errors (should be none)
    if kubectl logs $POD_NAME -n june-services 2>/dev/null | grep -q "Build time option.*not usable"; then
        echo "❌ Still has Keycloak build errors"
    else
        echo "✅ No Keycloak build option errors"
    fi
    
    echo ""
    echo "📊 Current pod status:"
    kubectl get pod $POD_NAME -n june-services
    
    echo ""
    echo "📋 Recent logs (looking for success indicators):"
    kubectl logs $POD_NAME -n june-services --tail=15 2>/dev/null | grep -E "(ready|started|Running|KC-SERVICES|ERROR|WARN)" || echo "No significant log entries yet"
    
else
    echo "⚠️ Pod not found yet"
fi

# Step 4: Test external access once ready
echo ""
echo "Step 4: Testing external access"
EXTERNAL_IP="34.44.89.92"  # From your previous output

echo "🌐 External IP: $EXTERNAL_IP"
echo "⏳ Testing connectivity (may take a few minutes for Keycloak to be ready)..."

# Test basic connectivity
if timeout 5s curl -s -f "http://$EXTERNAL_IP" >/dev/null 2>&1; then
    echo "✅ Keycloak admin console accessible at: http://$EXTERNAL_IP"
    echo "   Login: admin / admin123456"
else
    echo "⏳ Keycloak not ready yet (this is normal, wait 3-5 more minutes)"
    echo "   Test manually: curl http://$EXTERNAL_IP"
fi

# Clean up
rm -f keycloak-official-fix.yaml

echo ""
echo "🎯 What we fixed:"
echo "================="
echo "❌ BEFORE: Used '--db=postgres' with '--optimized' (incompatible)"
echo "✅ AFTER:  Used 'start-dev' with environment variables (official approach)"
echo ""
echo "❌ BEFORE: Complex JVM garbage collector settings (conflicting)"  
echo "✅ AFTER:  Simple, compatible JVM settings"
echo ""
echo "📖 This follows the official Keycloak Kubernetes documentation exactly"
echo ""
echo "⏰ Expected timeline:"
echo "  - Init container: 30 seconds (PostgreSQL check)"
echo "  - Keycloak startup: 2-5 minutes (much faster than Oracle!)"
echo "  - Ready for use: 3-6 minutes total"
echo ""
echo "🔧 Monitor with:"
echo "  kubectl logs -f deployment/june-idp-postgres -n june-services"