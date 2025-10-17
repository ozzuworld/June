#!/bin/bash

# Quick Fix Script for OpenCTI OpenSearch Connectivity
# This script provides immediate fixes for the current deployment issue

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

NAMESPACE="opencti"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check current status
log_info "Current OpenCTI pod status:"
kubectl get pods -n "$NAMESPACE" | grep opencti
echo

# Option 1: Update existing deployment with correct environment variables
fix_env_vars() {
    log_info "Fixing environment variables in existing deployment..."
    
    # Update OpenCTI server deployment
    local server_deployment
    server_deployment=$(kubectl get deployment -n "$NAMESPACE" -o name | grep opencti-server | head -1)
    
    if [ -n "$server_deployment" ]; then
        log_info "Updating $server_deployment with correct OpenSearch URL..."
        
        kubectl patch "$server_deployment" -n "$NAMESPACE" --type='merge' -p='{
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{
                            "name": "opencti",
                            "env": [
                                {
                                    "name": "ELASTICSEARCH__URL",
                                    "value": "http://opensearch-cluster-master:9200"
                                },
                                {
                                    "name": "ELASTICSEARCH__ENGINE_SELECTOR",
                                    "value": "opensearch"
                                },
                                {
                                    "name": "ELASTICSEARCH__ENGINE_CHECK",
                                    "value": "false"
                                }
                            ]
                        }]
                    }
                }
            }
        }'
        
        log_success "Environment variables updated"
    else
        log_error "No OpenCTI server deployment found"
        return 1
    fi
    
    # Update worker deployment if exists
    local worker_deployment
    worker_deployment=$(kubectl get deployment -n "$NAMESPACE" -o name | grep opencti-worker | head -1)
    
    if [ -n "$worker_deployment" ]; then
        log_info "Updating $worker_deployment with correct OpenSearch URL..."
        kubectl patch "$worker_deployment" -n "$NAMESPACE" --type='merge' -p='{
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{
                            "name": "opencti-worker",
                            "env": [
                                {
                                    "name": "ELASTICSEARCH__URL",
                                    "value": "http://opensearch-cluster-master:9200"
                                },
                                {
                                    "name": "ELASTICSEARCH__ENGINE_SELECTOR",
                                    "value": "opensearch"
                                },
                                {
                                    "name": "ELASTICSEARCH__ENGINE_CHECK",
                                    "value": "false"
                                }
                            ]
                        }]
                    }
                }
            }
        }'
        log_success "Worker environment variables updated"
    fi
}

# Option 2: Create service alias
create_service_alias() {
    log_info "Creating service alias for OpenSearch..."
    
    # Create a service that points to the existing OpenSearch
    kubectl apply -n "$NAMESPACE" -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: release-name-elasticsearch
  namespace: $NAMESPACE
  labels:
    app: opensearch-alias
spec:
  type: ClusterIP
  ports:
    - port: 9200
      targetPort: 9200
      name: http
  selector:
    app.kubernetes.io/name: opensearch
EOF
    
    log_success "Service alias created: release-name-elasticsearch -> opensearch-cluster-master"
}

# Option 3: Create endpoint and service manually
create_manual_endpoint() {
    log_info "Creating manual endpoint for OpenSearch..."
    
    # Get OpenSearch service IP
    local opensearch_ip
    opensearch_ip=$(kubectl get service opensearch-cluster-master -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}' 2>/dev/null)
    
    if [ -n "$opensearch_ip" ]; then
        log_info "Found OpenSearch service IP: $opensearch_ip"
        
        # Create service and endpoint
        kubectl apply -n "$NAMESPACE" -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: release-name-elasticsearch
  namespace: $NAMESPACE
spec:
  type: ClusterIP
  ports:
    - port: 9200
      targetPort: 9200
      name: http
  clusterIP: None
---
apiVersion: v1
kind: Endpoints
metadata:
  name: release-name-elasticsearch
  namespace: $NAMESPACE
subsets:
  - addresses:
      - ip: $opensearch_ip
    ports:
      - port: 9200
        name: http
EOF
        
        log_success "Manual endpoint created pointing to $opensearch_ip"
    else
        log_error "Could not find OpenSearch service IP"
        return 1
    fi
}

# Test connectivity
test_connectivity() {
    log_info "Testing OpenSearch connectivity..."
    
    # Test from a temporary pod
    kubectl run test-connectivity --rm -i --restart=Never --image=curlimages/curl:latest -n "$NAMESPACE" -- \
        sh -c "curl -s -o /dev/null -w '%{http_code}' http://opensearch-cluster-master:9200 && echo ' - Direct OpenSearch OK' || echo ' - Direct OpenSearch FAILED'" 2>/dev/null || true
    
    kubectl run test-connectivity-2 --rm -i --restart=Never --image=curlimages/curl:latest -n "$NAMESPACE" -- \
        sh -c "curl -s -o /dev/null -w '%{http_code}' http://release-name-elasticsearch:9200 && echo ' - Alias OpenSearch OK' || echo ' - Alias OpenSearch FAILED'" 2>/dev/null || true
}

# Restart OpenCTI pods
restart_opencti() {
    log_info "Restarting OpenCTI pods..."
    
    # Restart OpenCTI deployments
    kubectl rollout restart deployment -n "$NAMESPACE" -l app.kubernetes.io/name=opencti 2>/dev/null || true
    
    log_info "Waiting for pods to restart..."
    sleep 10
    
    # Show new pod status
    kubectl get pods -n "$NAMESPACE" | grep opencti
}

# Show status
show_status() {
    log_info "Current status after fixes:"
    echo
    
    log_info "Pods:"
    kubectl get pods -n "$NAMESPACE"
    echo
    
    log_info "Services:"
    kubectl get services -n "$NAMESPACE" | grep -E "(opensearch|elasticsearch)"
    echo
    
    log_info "Recent OpenCTI logs (last 10 lines):"
    kubectl logs -l app.kubernetes.io/name=opencti -n "$NAMESPACE" --tail=10 2>/dev/null || echo "No logs available"
}

# Main execution
main() {
    log_info "OpenCTI Quick Fix - Addressing OpenSearch connectivity issues"
    echo
    
    log_info "Available fixes:"
    echo "1. Update environment variables (recommended)"
    echo "2. Create service alias"
    echo "3. Create manual endpoint"
    echo "4. Run all fixes"
    echo "5. Just test connectivity"
    echo "6. Show current status"
    echo
    
    read -p "Choose fix (1-6): " choice
    
    case $choice in
        1)
            fix_env_vars
            restart_opencti
            ;;
        2)
            create_service_alias
            restart_opencti
            ;;
        3)
            create_manual_endpoint
            restart_opencti
            ;;
        4)
            fix_env_vars
            create_service_alias
            create_manual_endpoint
            restart_opencti
            ;;
        5)
            test_connectivity
            ;;
        6)
            show_status
            ;;
        *)
            log_error "Invalid choice"
            exit 1
            ;;
    esac
    
    echo
    test_connectivity
    echo
    show_status
    
    log_success "Quick fix completed!"
    log_info "Monitor the pods with: kubectl get pods -n $NAMESPACE -w"
    log_info "Check logs with: kubectl logs -f <pod-name> -n $NAMESPACE"
}

# Parse arguments
if [ "$1" = "--auto" ]; then
    log_info "Running automatic fix..."
    fix_env_vars
    create_service_alias
    restart_opencti
    test_connectivity
    show_status
else
    main
fi