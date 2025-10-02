#!/bin/bash
# Clean June Services Deployment Script
# This script ensures single deployments without duplicates

set -e

echo "======================================================"
echo "🚀 June Services Deployment Script"
echo "   Clean deployment with no duplicates"
echo "======================================================"

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
    print_status "error" "kubectl not found. Please install kubectl first."
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
echo "🧹 Step 1: Clean up any existing deployments"
echo "==============================================="

# Check if june-services namespace exists
if kubectl get namespace june-services &> /dev/null; then
    print_status "info" "Found june-services namespace"
    
    # List existing deployments
    EXISTING_DEPLOYMENTS=$(kubectl get deployments -n june-services --no-headers 2>/dev/null | wc -l)
    if [ "$EXISTING_DEPLOYMENTS" -gt 0 ]; then
        print_status "warn" "Found $EXISTING_DEPLOYMENTS existing deployments"
        echo ""
        kubectl get deployments -n june-services
        echo ""
        
        read -p "Do you want to delete existing deployments to start fresh? (y/n): " cleanup_confirm
        if [[ $cleanup_confirm == [yY] ]]; then
            print_status "info" "Cleaning up existing deployments..."
            
            # Delete deployments
            kubectl delete deployment --all -n june-services 2>/dev/null || true
            
            # Wait for pods to terminate
            print_status "info" "Waiting for pods to terminate..."
            kubectl wait --for=delete pods --all -n june-services --timeout=60s 2>/dev/null || true
            
            print_status "ok" "Cleanup completed"
        else
            print_status "warn" "Proceeding with existing deployments - may cause conflicts"
        fi
    else
        print_status "ok" "No existing deployments found"
    fi
else
    print_status "info" "june-services namespace doesn't exist yet - will be created"
fi

echo ""
echo "💾 Step 2: Deploy PostgreSQL Database"
echo "====================================="

# Deploy PostgreSQL first
if [ -f "k8s/postgresql-deployment.yaml" ]; then
    print_status "info" "Deploying PostgreSQL..."
    kubectl apply -f k8s/postgresql-deployment.yaml
    
    # Wait for PostgreSQL to be ready
    print_status "info" "Waiting for PostgreSQL to be ready..."
    kubectl wait --for=condition=ready pod -l app=postgresql -n june-services --timeout=300s || {
        print_status "warn" "PostgreSQL taking longer than expected, continuing..."
    }
    
    print_status "ok" "PostgreSQL deployed"
else
    print_status "warn" "PostgreSQL deployment file not found, skipping..."
fi

echo ""
echo "🚀 Step 3: Deploy June Services"
echo "==============================="

# Choose deployment method
echo "Choose deployment method:"
echo "1. Use complete-manifests.yaml (recommended)"
echo "2. Use individual deployment files"
read -p "Enter choice (1 or 2): " deploy_method

if [ "$deploy_method" = "1" ]; then
    # Method 1: Complete manifests
    if [ -f "k8s/complete-manifests.yaml" ]; then
        print_status "info" "Deploying all services using complete-manifests.yaml..."
        kubectl apply -f k8s/complete-manifests.yaml
        print_status "ok" "Services deployed using complete manifests"
    else
        print_status "error" "complete-manifests.yaml not found!"
        exit 1
    fi
elif [ "$deploy_method" = "2" ]; then
    # Method 2: Individual files
    print_status "info" "Deploying services using individual files..."
    
    # Deploy in order
    SERVICES=("june-stt" "june-tts" "june-orchestrator" "june-idp")
    
    for service in "${SERVICES[@]}"; do
        if [ -f "k8s/${service}-deployment.yaml" ]; then
            print_status "info" "Deploying $service..."
            kubectl apply -f "k8s/${service}-deployment.yaml"
        else
            print_status "warn" "Deployment file for $service not found, skipping..."
        fi
    done
    
    # Deploy ingress if exists
    if [ -f "k8s/ingress.yaml" ]; then
        print_status "info" "Deploying ingress..."
        kubectl apply -f k8s/ingress.yaml
    fi
    
    print_status "ok" "Services deployed using individual files"
else
    print_status "error" "Invalid choice. Exiting."
    exit 1
fi

echo ""
echo "🔍 Step 4: Verify Deployment"
echo "==========================="

# Wait a moment for deployments to be created
sleep 10

# Check deployments
print_status "info" "Checking deployment status..."
echo ""
kubectl get deployments -n june-services -o wide

echo ""
print_status "info" "Checking pod status..."
echo ""
kubectl get pods -n june-services -o wide

echo ""
print_status "info" "Checking services..."
echo ""
kubectl get services -n june-services

# Count replicas to ensure no duplicates
echo ""
print_status "info" "Verifying no duplicate replicas..."
DUPLICATE_COUNT=0
for deployment in $(kubectl get deployments -n june-services --no-headers | awk '{print $1}'); do
    RS_COUNT=$(kubectl get replicasets -n june-services -l app=$deployment --no-headers | wc -l)
    if [ "$RS_COUNT" -gt 1 ]; then
        print_status "warn" "$deployment has $RS_COUNT ReplicaSets (potential duplicates)"
        ((DUPLICATE_COUNT++))
    fi
done

if [ "$DUPLICATE_COUNT" -eq 0 ]; then
    print_status "ok" "No duplicate ReplicaSets found"
else
    print_status "warn" "Found potential duplicate ReplicaSets in $DUPLICATE_COUNT services"
fi

echo ""
echo "🎉======================================================"
echo "✅ June Services Deployment Complete!"
echo "======================================================"
echo ""
echo "📋 Deployment Summary:"
DEPLOYMENT_COUNT=$(kubectl get deployments -n june-services --no-headers | wc -l)
RUNNING_PODS=$(kubectl get pods -n june-services --no-headers | grep -c "Running" || echo "0")
PENDING_PODS=$(kubectl get pods -n june-services --no-headers | grep -c -E "Pending|ContainerCreating|PodInitializing" || echo "0")
FAILED_PODS=$(kubectl get pods -n june-services --no-headers | grep -c -E "Error|CrashLoopBackOff|ImagePullBackOff" || echo "0")

echo "  • Deployments: $DEPLOYMENT_COUNT"
echo "  • Running pods: $RUNNING_PODS"
if [ "$PENDING_PODS" -gt 0 ]; then
    echo "  • Pending pods: $PENDING_PODS"
fi
if [ "$FAILED_PODS" -gt 0 ]; then
    echo "  • Failed pods: $FAILED_PODS"
fi
echo ""
echo "🔍 Monitoring Commands:"
echo "  • Watch pods: kubectl get pods -n june-services -w"
echo "  • Check logs: kubectl logs -l app=<service-name> -n june-services"
echo "  • Describe pod: kubectl describe pod <pod-name> -n june-services"
echo "  • Port forward: kubectl port-forward svc/<service-name> <local-port>:<service-port> -n june-services"
echo ""
echo "======================================================"