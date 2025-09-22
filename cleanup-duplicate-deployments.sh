#!/bin/bash
# cleanup-duplicate-deployments.sh
# Remove conflicting Keycloak deployments

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }

log "🧹 Cleaning up duplicate Keycloak deployments..."

# Check what exists first
log "📋 Current deployments:"
echo "In default namespace:"
kubectl get all -n default | grep -E "(keycloak|postgres)" || echo "None found"
echo ""
echo "In june-services namespace:"
kubectl get all -n june-services | grep -E "(june-idp|postgresql)" || echo "None found"
echo ""

# Ask for confirmation
echo "This script will remove the conflicting resources in the DEFAULT namespace:"
echo "  - StatefulSet/keycloak"
echo "  - Deployment/postgres"
echo "  - Associated services, PVCs, etc."
echo ""
echo "The working june-idp and other June services in june-services namespace will be kept."
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log "Aborted."
    exit 0
fi

log "🗑️ Removing conflicting Keycloak StatefulSet in default namespace..."

# Remove StatefulSet keycloak
if kubectl get statefulset keycloak -n default >/dev/null 2>&1; then
    kubectl delete statefulset keycloak -n default
    success "Removed StatefulSet keycloak"
else
    log "StatefulSet keycloak not found (may already be deleted)"
fi

# Remove Service keycloak
if kubectl get service keycloak -n default >/dev/null 2>&1; then
    kubectl delete service keycloak -n default
    success "Removed Service keycloak"
else
    log "Service keycloak not found"
fi

# Remove postgres deployment in default namespace
if kubectl get deployment postgres -n default >/dev/null 2>&1; then
    kubectl delete deployment postgres -n default
    success "Removed Deployment postgres"
else
    log "Deployment postgres not found"
fi

# Remove postgres service in default namespace
if kubectl get service postgres -n default >/dev/null 2>&1; then
    kubectl delete service postgres -n default
    success "Removed Service postgres"
else
    log "Service postgres not found"
fi

# Remove any PVCs for keycloak in default namespace
log "🗑️ Removing PersistentVolumeClaims..."
kubectl delete pvc -n default -l app=keycloak 2>/dev/null || log "No keycloak PVCs found"
kubectl delete pvc -n default -l app=postgres 2>/dev/null || log "No postgres PVCs found"

# Remove any ConfigMaps
log "🗑️ Removing ConfigMaps..."
kubectl delete configmap -n default -l app=keycloak 2>/dev/null || log "No keycloak ConfigMaps found"

# Remove any Secrets
log "🗑️ Removing Secrets..."
kubectl delete secret -n default -l app=keycloak 2>/dev/null || log "No keycloak Secrets found"

log "⏳ Waiting for cleanup to complete..."
sleep 10

log "📋 Verifying cleanup - remaining resources in default namespace:"
kubectl get all -n default | grep -E "(keycloak|postgres)" || success "All conflicting resources removed!"

echo ""
log "📋 Verifying June services are still running in june-services namespace:"
kubectl get pods -n june-services

echo ""
success "Cleanup completed! Only the proper June services should remain."

log "🔍 To verify everything is working:"
echo "1. Check all pods are running: kubectl get pods -n june-services"
echo "2. Test services: ./test-deployment.sh"
echo "3. Access Keycloak admin: kubectl port-forward -n june-services service/june-idp 8080:8080"
echo "   Then visit: http://localhost:8080/auth/admin"