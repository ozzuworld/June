#!/bin/bash
set -e

echo "🔍 June Platform - Fresh Deployment Validation"
echo "==============================================="
echo "This script validates that all components are properly configured for fresh deployments."
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; }
info() { echo -e "${BLUE}ℹ️${NC} $1"; }

VALIDATION_ERRORS=0
VALIDATION_WARNINGS=0

# Check if we're in the right directory
if [ ! -f "install.sh" ] || [ ! -d "helm/june-platform" ]; then
    error "Please run this script from the June repository root directory"
    exit 1
fi

info "Validating repository configuration for fresh deployments..."
echo ""

# ============================================================================
# 1. Validate Helm Chart Structure
# ============================================================================

echo -e "${BLUE}📋 1. Helm Chart Structure${NC}"

if [ -f "helm/june-platform/Chart.yaml" ] || [ -f "helm/june-platform/chart.yaml" ]; then
    success "Helm chart definition found"
else
    error "Helm chart definition missing (Chart.yaml or chart.yaml)"
    ((VALIDATION_ERRORS++))
fi

if [ -f "helm/june-platform/values.yaml" ]; then
    success "Helm values file found"
else
    error "Helm values.yaml missing"
    ((VALIDATION_ERRORS++))
fi

if [ -d "helm/june-platform/templates" ]; then
    success "Helm templates directory found"
    
    # Check key templates
    REQUIRED_TEMPLATES=(
        "ingress.yaml"
        "june-orchestrator.yaml"
        "configmaps.yaml"
        "secrets.yaml"
    )
    
    for template in "${REQUIRED_TEMPLATES[@]}"; do
        if [ -f "helm/june-platform/templates/$template" ]; then
            success "Template $template found"
        else
            error "Template $template missing"
            ((VALIDATION_ERRORS++))
        fi
    done
else
    error "Helm templates directory missing"
    ((VALIDATION_ERRORS++))
fi

echo ""

# ============================================================================
# 2. Validate LiveKit SDK Configuration
# ============================================================================

echo -e "${BLUE}🔗 2. LiveKit SDK Configuration${NC}"

if [ -f "June/services/june-orchestrator/requirements.txt" ]; then
    if grep -q "livekit-api==0.8.0" June/services/june-orchestrator/requirements.txt; then
        success "LiveKit API SDK version 0.8.0 configured"
    else
        error "LiveKit API SDK version should be 0.8.0"
        echo "  Current: $(grep livekit-api June/services/june-orchestrator/requirements.txt || echo 'Not found')"
        ((VALIDATION_ERRORS++))
    fi
    
    if grep -q "livekit-protocol==0.8.0" June/services/june-orchestrator/requirements.txt; then
        success "LiveKit Protocol SDK version 0.8.0 configured"
    else
        error "LiveKit Protocol SDK version should be 0.8.0"
        echo "  Current: $(grep livekit-protocol June/services/june-orchestrator/requirements.txt || echo 'Not found')"
        ((VALIDATION_ERRORS++))
    fi
else
    error "Orchestrator requirements.txt not found"
    ((VALIDATION_ERRORS++))
fi

# Check if the LiveKit service code uses VideoGrants (not VideoGrant)
if [ -f "June/services/june-orchestrator/app/services/livekit_service.py" ]; then
    if grep -q "api.VideoGrants" June/services/june-orchestrator/app/services/livekit_service.py; then
        success "LiveKit service uses correct VideoGrants API"
    else
        error "LiveKit service should use api.VideoGrants (plural)"
        ((VALIDATION_ERRORS++))
    fi
else
    error "LiveKit service file not found"
    ((VALIDATION_ERRORS++))
fi

echo ""

# ============================================================================
# 3. Validate Ingress Configuration
# ============================================================================

echo -e "${BLUE}🌐 3. Ingress Configuration${NC}"

if [ -f "helm/june-platform/templates/ingress.yaml" ]; then
    # Check for livekit subdomain configuration
    if grep -q "livekit.{{ .Values.domains.primary }}" helm/june-platform/templates/ingress.yaml; then
        success "LiveKit subdomain routing configured"
    else
        error "LiveKit subdomain (livekit.domain.com) not configured in ingress"
        ((VALIDATION_ERRORS++))
    fi
    
    # Check for livekit-proxy service
    if grep -q "livekit-proxy" helm/june-platform/templates/ingress.yaml; then
        success "LiveKit proxy service referenced in ingress"
    else
        error "LiveKit proxy service not configured in ingress"
        ((VALIDATION_ERRORS++))
    fi
    
    # Check for TLS configuration including livekit subdomain
    if grep -q "livekit.{{ .Values.domains.primary }}" helm/june-platform/templates/ingress.yaml; then
        success "LiveKit domain included in TLS configuration"
    else
        warn "LiveKit domain may not be included in TLS certificate"
        ((VALIDATION_WARNINGS++))
    fi
    
    # Check for ExternalName service definition
    if grep -q "ExternalName" helm/june-platform/templates/ingress.yaml; then
        success "LiveKit proxy ExternalName service defined"
    else
        error "LiveKit proxy ExternalName service not defined"
        ((VALIDATION_ERRORS++))
    fi
else
    error "Ingress template not found"
    ((VALIDATION_ERRORS++))
fi

echo ""

# ============================================================================
# 4. Validate ConfigMap Configuration
# ============================================================================

echo -e "${BLUE}⚙️ 4. ConfigMap Configuration${NC}"

if [ -f "helm/june-platform/templates/configmaps.yaml" ]; then
    # Check LiveKit host configuration
    if grep -q "livekit-livekit-server.media.svc.cluster.local" helm/june-platform/templates/configmaps.yaml; then
        success "LiveKit internal host correctly configured"
    else
        error "LiveKit internal host should be livekit-livekit-server.media.svc.cluster.local"
        ((VALIDATION_ERRORS++))
    fi
    
    # Check public LiveKit URLs
    if grep -q "wss://livekit.{{ .Values.domains.primary }}" helm/june-platform/templates/configmaps.yaml; then
        success "Public LiveKit WebSocket URL correctly configured"
    else
        error "Public LiveKit WebSocket URL should use livekit subdomain"
        ((VALIDATION_ERRORS++))
    fi
else
    error "ConfigMaps template not found"
    ((VALIDATION_ERRORS++))
fi

echo ""

# ============================================================================
# 5. Validate Orchestrator Deployment
# ============================================================================

echo -e "${BLUE}🎯 5. Orchestrator Deployment${NC}"

if [ -f "helm/june-platform/templates/june-orchestrator.yaml" ]; then
    # Check environment variable names
    if grep -q "LIVEKIT_WS_URL" helm/june-platform/templates/june-orchestrator.yaml; then
        success "LIVEKIT_WS_URL environment variable configured"
    else
        error "LIVEKIT_WS_URL environment variable missing"
        ((VALIDATION_ERRORS++))
    fi
    
    if grep -q "LIVEKIT_API_KEY" helm/june-platform/templates/june-orchestrator.yaml; then
        success "LIVEKIT_API_KEY environment variable configured"
    else
        error "LIVEKIT_API_KEY environment variable missing"
        ((VALIDATION_ERRORS++))
    fi
    
    if grep -q "LIVEKIT_API_SECRET" helm/june-platform/templates/june-orchestrator.yaml; then
        success "LIVEKIT_API_SECRET environment variable configured"
    else
        error "LIVEKIT_API_SECRET environment variable missing"
        ((VALIDATION_ERRORS++))
    fi
    
    # Check if using correct external URL
    if grep -q "wss://livekit.{{ .Values.domains.primary }}" helm/june-platform/templates/june-orchestrator.yaml; then
        success "Orchestrator configured with correct external LiveKit URL"
    else
        error "Orchestrator should use external LiveKit URL (wss://livekit.domain.com)"
        ((VALIDATION_ERRORS++))
    fi
else
    error "Orchestrator deployment template not found"
    ((VALIDATION_ERRORS++))
fi

echo ""

# ============================================================================
# 6. Validate Kubernetes Manifests
# ============================================================================

echo -e "${BLUE}☸️ 6. Kubernetes Manifests${NC}"

if [ -d "k8s/livekit" ]; then
    success "LiveKit Kubernetes manifests directory found"
    
    if [ -f "k8s/livekit/livekit-values.yaml" ]; then
        success "LiveKit values file found"
    else
        warn "LiveKit values file not found (k8s/livekit/livekit-values.yaml)"
        ((VALIDATION_WARNINGS++))
    fi
else
    warn "LiveKit Kubernetes manifests directory not found"
    ((VALIDATION_WARNINGS++))
fi

if [ -d "k8s/stunner" ]; then
    success "STUNner Kubernetes manifests directory found"
else
    warn "STUNner Kubernetes manifests directory not found"
    ((VALIDATION_WARNINGS++))
fi

echo ""

# ============================================================================
# 7. Validate Installation Script
# ============================================================================

echo -e "${BLUE}🚀 7. Installation Script${NC}"

if [ -f "install.sh" ]; then
    success "Main installation script found"
    
    if grep -q "install_livekit" install.sh; then
        success "LiveKit installation step included"
    else
        error "LiveKit installation step missing from install.sh"
        ((VALIDATION_ERRORS++))
    fi
    
    if [ -x "install.sh" ]; then
        success "Installation script is executable"
    else
        warn "Installation script is not executable (run: chmod +x install.sh)"
        ((VALIDATION_WARNINGS++))
    fi
else
    error "Installation script not found"
    ((VALIDATION_ERRORS++))
fi

echo ""

# ============================================================================
# Summary
# ============================================================================

echo -e "${BLUE}📊 Validation Summary${NC}"
echo "==================="

if [ $VALIDATION_ERRORS -eq 0 ] && [ $VALIDATION_WARNINGS -eq 0 ]; then
    success "All validation checks passed! ✨"
    success "The repository is ready for fresh deployments."
elif [ $VALIDATION_ERRORS -eq 0 ]; then
    success "All critical checks passed!"
    warn "$VALIDATION_WARNINGS warnings found (non-critical)"
    info "The repository should work for fresh deployments."
else
    error "$VALIDATION_ERRORS errors found that must be fixed!"
    if [ $VALIDATION_WARNINGS -gt 0 ]; then
        warn "$VALIDATION_WARNINGS warnings also found."
    fi
    error "Please fix the errors before attempting fresh deployment."
fi

echo ""
echo -e "${BLUE}🛠️ Next Steps for Fresh Deployment:${NC}"
echo "1. Ensure DNS records point to your server IP:"
echo "   - domain.com        A    YOUR_SERVER_IP"
echo "   - *.domain.com      A    YOUR_SERVER_IP"
echo "2. Update config.env with your settings"
echo "3. Run: sudo ./install.sh"
echo "4. Monitor deployment: kubectl get pods --all-namespaces"
echo ""

if [ $VALIDATION_ERRORS -gt 0 ]; then
    exit 1
else
    exit 0
fi