#!/bin/bash
# Quick status checker for June K8s deployment

set -e

echo "🔍 June Kubernetes Deployment Status Check"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    local status=$1
    local message=$2
    case $status in
        "ok") echo -e "${GREEN}✅ $message${NC}" ;;
        "warn") echo -e "${YELLOW}⚠️  $message${NC}" ;;
        "error") echo -e "${RED}❌ $message${NC}" ;;
        "info") echo -e "${BLUE}ℹ️  $message${NC}" ;;
    esac
}

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    print_status "error" "kubectl not found. Please install kubectl."
    exit 1
fi

# Check cluster connectivity
print_status "info" "Checking cluster connectivity..."
if kubectl cluster-info &> /dev/null; then
    print_status "ok" "Cluster is accessible"
else
    print_status "error" "Cannot connect to Kubernetes cluster"
    exit 1
fi

echo ""
echo "🏗️ Infrastructure Status"
echo "========================"

# Check nodes
NODE_STATUS=$(kubectl get nodes --no-headers | awk '{print $2}' | head -1)
if [ "$NODE_STATUS" = "Ready" ]; then
    print_status "ok" "Node is Ready"
else
    print_status "warn" "Node status: $NODE_STATUS"
fi

# Check namespaces
if kubectl get namespace june &> /dev/null; then
    print_status "ok" "June namespace exists"
else
    print_status "warn" "June namespace not found"
fi

# Check ingress controller
if kubectl get pods -n ingress-nginx | grep -q "Running"; then
    print_status "ok" "Ingress controller is running"
else
    print_status "warn" "Ingress controller not found or not running"
fi

echo ""
echo "🚀 June Services Status"
echo "======================"

NAMESPACE="june"
SERVICES=("june-stt" "june-tts" "june-orchestrator" "june-idp" "june-web" "june-dark")

for service in "${SERVICES[@]}"; do
    if kubectl get deployment "$service" -n "$NAMESPACE" &> /dev/null; then
        READY=$(kubectl get deployment "$service" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        DESIRED=$(kubectl get deployment "$service" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")
        
        if [ "$READY" = "$DESIRED" ] && [ "$READY" != "0" ]; then
            print_status "ok" "$service: $READY/$DESIRED replicas ready"
        else
            print_status "warn" "$service: $READY/$DESIRED replicas ready"
        fi
    else
        print_status "error" "$service: deployment not found"
    fi
done

echo ""
echo "📊 Pod Details"
echo "=============="

kubectl get pods -n "$NAMESPACE" -o wide 2>/dev/null || print_status "warn" "No pods found in namespace $NAMESPACE"

echo ""
echo "🌐 Network Status"
echo "================="

# Check services
echo "Services:"
kubectl get services -n "$NAMESPACE" 2>/dev/null || print_status "warn" "No services found"

echo ""
echo "Ingress:"
kubectl get ingress -n "$NAMESPACE" 2>/dev/null || print_status "warn" "No ingress found"

echo ""
echo "🔐 Configuration Status"
echo "======================"

# Check secrets
if kubectl get secret june-secrets -n "$NAMESPACE" &> /dev/null; then
    print_status "ok" "June secrets exist"
else
    print_status "warn" "June secrets not found"
fi

if kubectl get secret dockerhub-secret -n "$NAMESPACE" &> /dev/null; then
    print_status "ok" "Docker Hub secret exists"
else
    print_status "warn" "Docker Hub secret not found"
fi

# Check configmaps
if kubectl get configmap june-config -n "$NAMESPACE" &> /dev/null; then
    print_status "ok" "June config exists"
else
    print_status "warn" "June config not found"
fi

echo ""
echo "💾 Storage Status"
echo "================="

# Check persistent volumes
PV_COUNT=$(kubectl get pv | grep -c "local-storage" 2>/dev/null || echo "0")
PVC_COUNT=$(kubectl get pvc -n "$NAMESPACE" 2>/dev/null | grep -c "Bound" || echo "0")

print_status "info" "Persistent Volumes: $PV_COUNT"
print_status "info" "Bound PVCs: $PVC_COUNT"

echo ""
echo "🔄 Recent Events"
echo "================"

echo "Recent events in $NAMESPACE namespace:"
kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' | tail -10 2>/dev/null || print_status "warn" "No events found"

echo ""
echo "🌍 External Access"
echo "=================="

# Get external IP
EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || echo "Unable to detect")
print_status "info" "External IP: $EXTERNAL_IP"

# Check if ingress has external access
INGRESS_IP=$(kubectl get ingress -n "$NAMESPACE" -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "Not available")
if [ "$INGRESS_IP" != "Not available" ]; then
    print_status "ok" "Ingress external IP: $INGRESS_IP"
else
    print_status "info" "Ingress external IP: Not available (using NodePort or ClusterIP)"
fi

echo ""
echo "🎯 Quick Actions"
echo "================"
echo "To view logs for a service:"
echo "  kubectl logs -l app=<service-name> -n $NAMESPACE"
echo ""
echo "To restart a deployment:"
echo "  kubectl rollout restart deployment/<service-name> -n $NAMESPACE"
echo ""
echo "To access a service locally:"
echo "  kubectl port-forward svc/<service-name> <local-port>:<service-port> -n $NAMESPACE"
echo ""
echo "To check resource usage:"
echo "  kubectl top pods -n $NAMESPACE"
echo ""

# Summary
echo "📋 Summary"
echo "=========="

TOTAL_SERVICES=${#SERVICES[@]}
RUNNING_SERVICES=0

for service in "${SERVICES[@]}"; do
    if kubectl get deployment "$service" -n "$NAMESPACE" &> /dev/null; then
        READY=$(kubectl get deployment "$service" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        DESIRED=$(kubectl get deployment "$service" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")
        
        if [ "$READY" = "$DESIRED" ] && [ "$READY" != "0" ]; then
            ((RUNNING_SERVICES++))
        fi
    fi
done

if [ "$RUNNING_SERVICES" = "$TOTAL_SERVICES" ]; then
    print_status "ok" "All services are running ($RUNNING_SERVICES/$TOTAL_SERVICES)"
else
    print_status "warn" "Some services need attention ($RUNNING_SERVICES/$TOTAL_SERVICES running)"
fi

echo "=========================================="