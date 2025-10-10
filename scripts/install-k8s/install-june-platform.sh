#!/bin/bash
# June Platform Installation Orchestrator
# Coordinates all installation steps in the correct order
# Usage: ./install-june-platform.sh [options]

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }
log_step()    { echo -e "${CYAN}🔹 $1${NC}"; }

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="/root/.june-config"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Parse arguments
SKIP_CORE=false
SKIP_NETWORKING=false
SKIP_GPU=false
SKIP_GITHUB=false
SKIP_DEPLOY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-core) SKIP_CORE=true; shift ;;
        --skip-networking) SKIP_NETWORKING=true; shift ;;
        --skip-gpu) SKIP_GPU=true; shift ;;
        --skip-github) SKIP_GITHUB=true; shift ;;
        --skip-deploy) SKIP_DEPLOY=true; shift ;;
        --help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --skip-core        Skip core infrastructure (K8s, ingress, cert-manager)"
            echo "  --skip-networking  Skip networking (MetalLB, STUNner)"
            echo "  --skip-gpu         Skip GPU operator installation"
            echo "  --skip-github      Skip GitHub Actions runner setup"
            echo "  --skip-deploy      Skip manifest generation and deployment"
            echo "  --help             Show this help message"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo ""
echo "══════════════════════════════════════════════════"
echo "🚀 June Platform Installation Orchestrator"
echo "══════════════════════════════════════════════════"
echo ""
echo "This will install:"
if [ "$SKIP_CORE" = false ]; then
    echo "  ✓ Core Infrastructure (Docker, K8s, ingress, cert-manager)"
else
    echo "  ⊘ Core Infrastructure (skipped)"
fi

if [ "$SKIP_NETWORKING" = false ]; then
    echo "  ✓ Networking (MetalLB, STUNner with Gateway API v1)"
else
    echo "  ⊘ Networking (skipped)"
fi

if [ "$SKIP_GPU" = false ]; then
    echo "  ✓ GPU Operator (optional)"
else
    echo "  ⊘ GPU Operator (skipped)"
fi

if [ "$SKIP_GITHUB" = false ]; then
    echo "  ✓ GitHub Actions Runner (optional)"
else
    echo "  ⊘ GitHub Actions Runner (skipped)"
fi

if [ "$SKIP_DEPLOY" = false ]; then
    echo "  ✓ Manifest Processing & Deployment"
else
    echo "  ⊘ Manifest Processing & Deployment (skipped)"
fi

echo ""
read -p "Continue with installation? (y/n): " CONFIRM
if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 0
fi

# Create config directory
mkdir -p "$CONFIG_DIR"

# ============================================================================
# STEP 1: PREREQUISITES CHECK
# ============================================================================

log_step "Step 1: Checking prerequisites..."

# Check OS
if [ ! -f /etc/os-release ]; then
    log_error "Cannot detect OS"
    exit 1
fi

source /etc/os-release
if [[ "$ID" != "ubuntu" ]]; then
    log_warning "This script is designed for Ubuntu. Detected: $ID"
    read -p "Continue anyway? (y/n): " CONTINUE
    [[ ! $CONTINUE =~ ^[Yy]$ ]] && exit 0
fi

# Install basic tools
log_info "Installing basic tools..."
apt-get update -qq
apt-get install -y curl wget git jq bc apt-transport-https ca-certificates gnupg lsb-release

log_success "Prerequisites OK"

# ============================================================================
# STEP 2: CORE INFRASTRUCTURE
# ============================================================================

if [ "$SKIP_CORE" = false ]; then
    log_step "Step 2: Installing core infrastructure..."
    
    if [ -f "$SCRIPT_DIR/install-core-infrastructure.sh" ]; then
        bash "$SCRIPT_DIR/install-core-infrastructure.sh"
    else
        log_error "install-core-infrastructure.sh not found!"
        exit 1
    fi
    
    log_success "Core infrastructure installed!"
else
    log_info "Skipping core infrastructure (--skip-core)"
fi

# ============================================================================
# STEP 3: NETWORKING (METALLB + STUNNER)
# ============================================================================

if [ "$SKIP_NETWORKING" = false ]; then
    log_step "Step 3: Installing networking (MetalLB + STUNner)..."
    
    if [ -f "$SCRIPT_DIR/install-networking.sh" ]; then
        bash "$SCRIPT_DIR/install-networking.sh"
    else
        log_error "install-networking.sh not found!"
        exit 1
    fi
    
    log_success "Networking installed!"
else
    log_info "Skipping networking (--skip-networking)"
fi

# ============================================================================
# STEP 4: GPU OPERATOR (OPTIONAL)
# ============================================================================

if [ "$SKIP_GPU" = false ]; then
    log_step "Step 4: GPU Operator installation..."
    
    read -p "Install GPU Operator with time-slicing? (y/n): " INSTALL_GPU
    
    if [[ $INSTALL_GPU =~ ^[Yy]$ ]]; then
        if [ -f "$SCRIPT_DIR/install-gpu-operator.sh" ]; then
            bash "$SCRIPT_DIR/install-gpu-operator.sh"
        else
            log_warning "install-gpu-operator.sh not found, skipping GPU setup"
        fi
    else
        log_info "Skipping GPU Operator installation"
    fi
else
    log_info "Skipping GPU Operator (--skip-gpu)"
fi

# ============================================================================
# STEP 5: GITHUB ACTIONS RUNNER (OPTIONAL)
# ============================================================================

if [ "$SKIP_GITHUB" = false ]; then
    log_step "Step 5: GitHub Actions Runner setup..."
    
    read -p "Install GitHub Actions Runner? (y/n): " INSTALL_RUNNER
    
    if [[ $INSTALL_RUNNER =~ ^[Yy]$ ]]; then
        if [ -f "$SCRIPT_DIR/install-github-runner.sh" ]; then
            bash "$SCRIPT_DIR/install-github-runner.sh"
        else
            log_warning "install-github-runner.sh not found, skipping runner setup"
        fi
    else
        log_info "Skipping GitHub Actions Runner installation"
    fi
else
    log_info "Skipping GitHub Actions Runner (--skip-github)"
fi

# ============================================================================
# STEP 6: APPLICATION SECRETS
# ============================================================================

log_step "Step 6: Creating application secrets..."

# Load existing config
if [ -f "$CONFIG_DIR/secrets.env" ]; then
    source "$CONFIG_DIR/secrets.env"
fi

if [ -z "$GEMINI_API_KEY" ]; then
    echo ""
    echo "Get your Gemini API key from:"
    echo "https://makersuite.google.com/app/apikey"
    echo ""
    read -p "Gemini API Key: " GEMINI_API_KEY
    
    # Save to config
    cat > "$CONFIG_DIR/secrets.env" << EOF
GEMINI_API_KEY=$GEMINI_API_KEY
EOF
    chmod 600 "$CONFIG_DIR/secrets.env"
fi

# Ensure june-services namespace exists
kubectl create namespace june-services || true

# Create Kubernetes secret
kubectl create secret generic june-secrets \
    --from-literal=gemini-api-key="$GEMINI_API_KEY" \
    --from-literal=keycloak-client-secret="PLACEHOLDER" \
    --namespace=june-services \
    --dry-run=client -o yaml | kubectl apply -f -

log_success "Application secrets created!"

# ============================================================================
# STEP 7: MANIFEST PROCESSING AND DEPLOYMENT
# ============================================================================

if [ "$SKIP_DEPLOY" = false ]; then
    log_step "Step 7: Processing manifests and deploying June services..."
    
    # Check if template processing script exists
    TEMPLATE_SCRIPT="$REPO_ROOT/scripts/generate-manifests.sh"
    if [ -f "$TEMPLATE_SCRIPT" ]; then
        log_info "Running manifest template processing..."
        bash "$TEMPLATE_SCRIPT"
        
        # Check if processed manifest was created
        PROCESSED_MANIFEST="$REPO_ROOT/k8s/complete-manifests-processed.yaml"
        if [ -f "$PROCESSED_MANIFEST" ]; then
            log_info "Deploying June services..."
            kubectl apply -f "$PROCESSED_MANIFEST"
            log_success "June services deployed!"
        else
            log_error "Processed manifest not found at: $PROCESSED_MANIFEST"
            exit 1
        fi
    else
        log_warning "Template processing script not found: $TEMPLATE_SCRIPT"
        log_info "Attempting to deploy original manifest..."
        
        ORIGINAL_MANIFEST="$REPO_ROOT/k8s/complete-manifests.yaml"
        if [ -f "$ORIGINAL_MANIFEST" ]; then
            kubectl apply -f "$ORIGINAL_MANIFEST"
            log_warning "Deployed original manifest - may need manual domain configuration"
        else
            log_error "No manifest found to deploy!"
            exit 1
        fi
    fi
else
    log_info "Skipping manifest processing and deployment (--skip-deploy)"
fi

# ============================================================================
# FINAL SUMMARY
# ============================================================================

# Load all configuration for summary
if [ -f "$CONFIG_DIR/infrastructure.env" ]; then
    source "$CONFIG_DIR/infrastructure.env"
fi
if [ -f "$CONFIG_DIR/domain-config.env" ]; then
    source "$CONFIG_DIR/domain-config.env"
fi
if [ -f "$CONFIG_DIR/networking.env" ]; then
    source "$CONFIG_DIR/networking.env"
fi

EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo "══════════════════════════════════════════════════"
log_success "🎉 June Platform Installation Complete!"
echo "══════════════════════════════════════════════════"
echo ""
echo "✅ Installed Components:"
echo "  • Core Infrastructure (K8s, ingress-nginx, cert-manager)"
echo "  • Networking (MetalLB, STUNner with Gateway API v1)"
if [[ $INSTALL_GPU =~ ^[Yy]$ ]]; then
    echo "  • GPU Operator with time-slicing"
fi
if [[ $INSTALL_RUNNER =~ ^[Yy]$ ]]; then
    echo "  • GitHub Actions Runner"
fi
if [ "$SKIP_DEPLOY" = false ]; then
    echo "  • June Services (deployed)"
else
    echo "  • June Services (ready for deployment)"
fi
echo "  • Application secrets"
echo ""
echo "🌍 Cluster Information:"
echo "  External IP: $EXTERNAL_IP"
echo "  Namespace: june-services"
echo ""
echo "🌐 Domain Configuration:"
echo "  Primary: ${PRIMARY_DOMAIN:-not configured}"
echo "  API: ${API_DOMAIN:-not configured}"
echo "  IDP: ${IDP_DOMAIN:-not configured}"
echo "  STT: ${STT_DOMAIN:-not configured}"
echo "  TTS: ${TTS_DOMAIN:-not configured}"
echo "  Certificate: ${CERT_SECRET_NAME:-not configured}"
echo ""
echo "🔗 STUNner Configuration:"
echo "  TURN Domain: ${TURN_DOMAIN:-not configured}"
echo "  Username: ${TURN_USERNAME:-not configured}"
echo "  Password: ${TURN_PASSWORD:0:3}***"
if [ -n "$STUNNER_LB_IP" ] && [ "$STUNNER_LB_IP" != "pending" ]; then
    echo "  LoadBalancer IP: $STUNNER_LB_IP"
fi
echo ""
echo "📁 Configuration Files:"
echo "  Infrastructure: $CONFIG_DIR/infrastructure.env"
echo "  Networking: $CONFIG_DIR/networking.env"
echo "  Domains: $CONFIG_DIR/domain-config.env"
echo "  Secrets: $CONFIG_DIR/secrets.env"
if [ -f "$CONFIG_DIR/ice-servers.json" ]; then
    echo "  ICE Servers: $CONFIG_DIR/ice-servers.json"
fi
echo ""
echo "📋 Next Steps:"
echo ""
echo "1. Configure DNS records to point to $EXTERNAL_IP:"
echo "   ${PRIMARY_DOMAIN:-your-domain.com} A $EXTERNAL_IP"
echo "   *.${PRIMARY_DOMAIN:-your-domain.com} A $EXTERNAL_IP"
echo ""
if [ "$SKIP_DEPLOY" = true ]; then
    echo "2. Process and deploy manifests:"
    echo "   bash scripts/generate-manifests.sh"
    echo "   kubectl apply -f k8s/complete-manifests-processed.yaml"
    echo ""
    echo "3. Monitor deployment:"
else
    echo "2. Monitor deployment:"
fi
echo "   kubectl get pods -n june-services -w"
echo ""
if [ "$SKIP_NETWORKING" = false ]; then
    echo "3. Test STUNner connectivity:"
    echo "   python3 scripts/test-turn-server.py"
    echo ""
fi
echo "🔍 Useful Commands:"
echo "  # Check cluster status"
echo "  kubectl cluster-info"
echo ""
echo "  # Check all services"
echo "  kubectl get all -n june-services"
echo ""
if [ "$SKIP_NETWORKING" = false ]; then
    echo "  # Check STUNner Gateway"
    echo "  kubectl get gateway -n stunner"
    echo "  kubectl get svc -n stunner"
    echo ""
fi
echo "  # View logs"
echo "  kubectl logs -n june-services -l app=june-orchestrator --tail=50"
if [ "$SKIP_NETWORKING" = false ]; then
    echo "  kubectl logs -n stunner-system -l app.kubernetes.io/name=stunner-gateway-operator"
fi
echo ""
echo "  # Check certificates"
echo "  kubectl get certificates -n june-services"
echo "  kubectl describe certificate ${CERT_SECRET_NAME:-allsafe-wildcard} -n june-services"
echo ""
echo "══════════════════════════════════════════════════"
echo "📖 Documentation:"
echo "  June: https://github.com/ozzuworld/June"
echo "  STUNner: https://docs.l7mp.io"
echo "  Gateway API: https://gateway-api.sigs.k8s.io"
echo "══════════════════════════════════════════════════"