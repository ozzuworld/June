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

# Parse arguments
SKIP_CORE=false
SKIP_NETWORKING=false
SKIP_GPU=false
SKIP_GITHUB=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-core) SKIP_CORE=true; shift ;;
        --skip-networking) SKIP_NETWORKING=true; shift ;;
        --skip-gpu) SKIP_GPU=true; shift ;;
        --skip-github) SKIP_GITHUB=true; shift ;;
        --help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --skip-core        Skip core infrastructure (K8s, ingress, cert-manager)"
            echo "  --skip-networking  Skip networking (MetalLB, STUNner)"
            echo "  --skip-gpu         Skip GPU operator installation"
            echo "  --skip-github      Skip GitHub Actions runner setup"
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
    echo "  ✓ Networking (MetalLB, STUNner with Gateway API v1alpha2)"
else
    echo "  ⊘ Networking (skipped)"
fi

if [ "$SKIP_GPU" = false ]; then
    echo "  ✓ GPU Operator (optional)"
else
    echo "  ⊘ GPU Operator (skipped)"
fi

if [ "$SKIP_GITHUB" = false ]; then
    echo "  ✓ GitHub Actions Runner"
else
    echo "  ⊘ GitHub Actions Runner (skipped)"
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
# STEP 5: GITHUB ACTIONS RUNNER
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
# STEP 6: DOMAIN & CERTIFICATES CONFIGURATION
# ============================================================================

log_step "Step 6: Domain and certificate configuration..."

if [ -f "$CONFIG_DIR/infrastructure.env" ]; then
    source "$CONFIG_DIR/infrastructure.env"
fi

# Ensure june-services namespace exists
kubectl create namespace june-services || true

# Check if domain config exists
if [ -f "$CONFIG_DIR/domain-config.env" ]; then
    log_info "Loading existing domain configuration..."
    source "$CONFIG_DIR/domain-config.env"
    echo ""
    echo "Current domain configuration:"
    echo "  Primary domain: $PRIMARY_DOMAIN"
    echo "  API domain: $API_DOMAIN"
    echo "  IDP domain: $IDP_DOMAIN"
    echo ""
    read -p "Use existing configuration? (y/n): " USE_EXISTING
    if [[ ! $USE_EXISTING =~ ^[Yy]$ ]]; then
        rm -f "$CONFIG_DIR/domain-config.env"
    fi
fi

if [ ! -f "$CONFIG_DIR/domain-config.env" ]; then
    log_info "Domain configuration setup..."
    echo ""
    echo "🌐 Enter your domain information:"
    echo ""
    
    read -p "Primary domain (e.g., example.com): " PRIMARY_DOMAIN
    while [ -z "$PRIMARY_DOMAIN" ]; do
        echo "Primary domain is required!"
        read -p "Primary domain (e.g., example.com): " PRIMARY_DOMAIN
    done
    
    read -p "API subdomain [api]: " API_SUBDOMAIN
    API_SUBDOMAIN=${API_SUBDOMAIN:-api}
    
    read -p "IDP subdomain [idp]: " IDP_SUBDOMAIN
    IDP_SUBDOMAIN=${IDP_SUBDOMAIN:-idp}
    
    read -p "STT subdomain [stt]: " STT_SUBDOMAIN
    STT_SUBDOMAIN=${STT_SUBDOMAIN:-stt}
    
    read -p "TTS subdomain [tts]: " TTS_SUBDOMAIN
    TTS_SUBDOMAIN=${TTS_SUBDOMAIN:-tts}
    
    # Construct full domains
    API_DOMAIN="${API_SUBDOMAIN}.${PRIMARY_DOMAIN}"
    IDP_DOMAIN="${IDP_SUBDOMAIN}.${PRIMARY_DOMAIN}"
    STT_DOMAIN="${STT_SUBDOMAIN}.${PRIMARY_DOMAIN}"
    TTS_DOMAIN="${TTS_SUBDOMAIN}.${PRIMARY_DOMAIN}"
    WILDCARD_DOMAIN="*.${PRIMARY_DOMAIN}"
    CERT_SECRET_NAME="${PRIMARY_DOMAIN//./-}-wildcard-tls"
    
    # Save domain config
    cat > "$CONFIG_DIR/domain-config.env" << EOF
PRIMARY_DOMAIN=$PRIMARY_DOMAIN
API_SUBDOMAIN=$API_SUBDOMAIN
IDP_SUBDOMAIN=$IDP_SUBDOMAIN
STT_SUBDOMAIN=$STT_SUBDOMAIN
TTS_SUBDOMAIN=$TTS_SUBDOMAIN
API_DOMAIN=$API_DOMAIN
IDP_DOMAIN=$IDP_DOMAIN
STT_DOMAIN=$STT_DOMAIN
TTS_DOMAIN=$TTS_DOMAIN
WILDCARD_DOMAIN=$WILDCARD_DOMAIN
CERT_SECRET_NAME=$CERT_SECRET_NAME
EOF
    chmod 600 "$CONFIG_DIR/domain-config.env"
    
    log_success "Domain configuration saved!"
fi

# Load the domain config
source "$CONFIG_DIR/domain-config.env"

echo ""
echo "🌐 Using domains:"
echo "  Primary: $PRIMARY_DOMAIN"
echo "  Wildcard: $WILDCARD_DOMAIN"
echo "  API: $API_DOMAIN"
echo "  IDP: $IDP_DOMAIN"
echo "  STT: $STT_DOMAIN"
echo "  TTS: $TTS_DOMAIN"
echo "  Certificate secret: $CERT_SECRET_NAME"
echo ""

# ============================================================================
# STEP 7: LET'S ENCRYPT CONFIGURATION
# ============================================================================

log_info "Setting up Let's Encrypt ClusterIssuer..."

if [ -z "$LETSENCRYPT_EMAIL" ]; then
    read -p "Let's Encrypt email address: " LETSENCRYPT_EMAIL
    while [ -z "$LETSENCRYPT_EMAIL" ]; do
        echo "Email is required for Let's Encrypt!"
        read -p "Let's Encrypt email address: " LETSENCRYPT_EMAIL
    done
fi

# Check if we need Cloudflare API token for wildcard
echo ""
echo "For wildcard certificates (*.${PRIMARY_DOMAIN}), we need DNS validation."
echo "This requires a Cloudflare API token if your domain uses Cloudflare DNS."
echo ""
read -p "Is your domain (${PRIMARY_DOMAIN}) using Cloudflare DNS? (y/n): " USES_CLOUDFLARE

if [[ $USES_CLOUDFLARE =~ ^[Yy]$ ]]; then
    # Cloudflare setup
    if [ -z "$CLOUDFLARE_API_TOKEN" ]; then
        echo ""
        echo "📋 To get your Cloudflare API token:"
        echo "   1. Go to https://dash.cloudflare.com/profile/api-tokens"
        echo "   2. Click 'Create Token'"
        echo "   3. Use 'Edit zone DNS' template"
        echo "   4. Select your domain zone"
        echo "   5. Copy the token"
        echo ""
        read -p "Cloudflare API Token: " CLOUDFLARE_API_TOKEN
        while [ -z "$CLOUDFLARE_API_TOKEN" ]; do
            echo "API token is required for DNS validation!"
            read -p "Cloudflare API Token: " CLOUDFLARE_API_TOKEN
        done
    fi
    
    # Create Cloudflare API token secret
    kubectl create secret generic cloudflare-api-token \
        --from-literal=api-token="$CLOUDFLARE_API_TOKEN" \
        --namespace=cert-manager \
        --dry-run=client -o yaml | kubectl apply -f -
    
    # Production issuer with Cloudflare DNS
    cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: $LETSENCRYPT_EMAIL
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
      selector:
        dnsNames:
        - "${PRIMARY_DOMAIN}"
        - "*.${PRIMARY_DOMAIN}"
EOF
    
    log_success "ClusterIssuer created with Cloudflare DNS validation"
    
else
    # HTTP validation only (no wildcard support)
    log_warning "Without DNS validation, wildcard certificates are not possible."
    log_warning "Using HTTP validation - you'll need individual certificates for each subdomain."
    
    cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: $LETSENCRYPT_EMAIL
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
EOF
    
    log_success "ClusterIssuer created with HTTP validation"
fi

# ============================================================================
# STEP 8: CERTIFICATE MANAGEMENT
# ============================================================================

log_step "Step 8: Certificate setup..."

echo ""
echo "🔐 Certificate options:"
echo "1) Create new wildcard certificate for *.${PRIMARY_DOMAIN}"
echo "2) Restore certificate from backup (paste YAML)"
echo "3) Skip certificate creation (manual setup later)"
echo ""
read -p "Choose option (1/2/3): " CERT_CHOICE

case $CERT_CHOICE in
    1)
        log_info "Creating new wildcard certificate..."
        
        if [[ ! $USES_CLOUDFLARE =~ ^[Yy]$ ]]; then
            log_error "Wildcard certificates require DNS validation (Cloudflare)!"
            log_error "Please choose option 2 to restore a certificate or configure Cloudflare."
            exit 1
        fi
        
        # Delete existing certificate if it exists
        kubectl delete certificate "$CERT_SECRET_NAME" -n june-services 2>/dev/null || true
        kubectl delete secret "$CERT_SECRET_NAME" -n june-services 2>/dev/null || true
        
        # Create wildcard certificate
        cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: $CERT_SECRET_NAME
  namespace: june-services
spec:
  secretName: $CERT_SECRET_NAME
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - "$PRIMARY_DOMAIN"
  - "*.${PRIMARY_DOMAIN}"
EOF
        
        log_success "Wildcard certificate created! Waiting for issuance..."
        
        # Wait for certificate to be ready
        log_info "Waiting for certificate to be issued (this may take 2-5 minutes)..."
        for i in {1..60}; do
            CERT_READY=$(kubectl get certificate "$CERT_SECRET_NAME" -n june-services -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "False")
            if [ "$CERT_READY" = "True" ]; then
                log_success "Certificate issued successfully!"
                break
            fi
            
            if [ $((i % 10)) -eq 0 ]; then
                log_info "Still waiting for certificate... (${i}/60)"
                kubectl describe certificate "$CERT_SECRET_NAME" -n june-services | grep -A 5 "Events:"
            fi
            sleep 10
        done
        
        if [ "$CERT_READY" != "True" ]; then
            log_warning "Certificate is taking longer than expected to issue."
            log_warning "You can check the status with: kubectl describe certificate $CERT_SECRET_NAME -n june-services"
        fi
        ;;
        
    2)
        log_info "Certificate backup restoration..."
        echo ""
        echo "📋 Paste your certificate backup YAML below."
        echo "This should include both the Certificate and Secret resources."
        echo "Press Ctrl+D on a new line when finished:"
        echo ""
        echo "--- (paste below this line) ---"
        
        # Create temporary file for the backup
        BACKUP_FILE=$(mktemp)
        
        # Read multiline input until EOF
        cat > "$BACKUP_FILE"
        
        echo ""
        log_info "Applying certificate backup..."
        
        # Apply the backup
        if kubectl apply -f "$BACKUP_FILE"; then
            log_success "Certificate restored successfully!"
            
            # Verify the certificate exists
            if kubectl get secret "$CERT_SECRET_NAME" -n june-services &>/dev/null; then
                log_success "Certificate secret '$CERT_SECRET_NAME' found in june-services namespace"
            else
                log_warning "Certificate secret not found with expected name '$CERT_SECRET_NAME'"
                echo "Available secrets in june-services:"
                kubectl get secrets -n june-services | grep tls || echo "No TLS secrets found"
            fi
        else
            log_error "Failed to apply certificate backup!"
            log_error "Please check the YAML format and try again."
        fi
        
        # Clean up temp file
        rm -f "$BACKUP_FILE"
        ;;
        
    3)
        log_info "Skipping certificate creation."
        log_warning "You'll need to create the certificate '$CERT_SECRET_NAME' manually in the june-services namespace."
        ;;
        
    *)
        log_error "Invalid choice. Exiting."
        exit 1
        ;;
esac

# ============================================================================
# STEP 9: APPLICATION SECRETS
# ============================================================================

log_step "Step 9: Creating application secrets..."

# Gemini API key
if [ -f "$CONFIG_DIR/secrets.env" ]; then
    source "$CONFIG_DIR/secrets.env"
fi

if [ -z "$GEMINI_API_KEY" ]; then
    echo ""
    echo "🤖 Get your Gemini API key from:"
    echo "   https://makersuite.google.com/app/apikey"
    echo ""
    read -p "Gemini API Key (or press Enter to skip): " GEMINI_API_KEY
    
    # Save to config if provided
    if [ -n "$GEMINI_API_KEY" ]; then
        cat > "$CONFIG_DIR/secrets.env" << EOF
GEMINI_API_KEY=$GEMINI_API_KEY
LETSENCRYPT_EMAIL=$LETSENCRYPT_EMAIL
CLOUDFLARE_API_TOKEN=$CLOUDFLARE_API_TOKEN
EOF
        chmod 600 "$CONFIG_DIR/secrets.env"
    fi
fi

# Create Kubernetes secret
kubectl create secret generic june-secrets \
    --from-literal=gemini-api-key="${GEMINI_API_KEY:-PLACEHOLDER}" \
    --from-literal=keycloak-client-secret="PLACEHOLDER" \
    --namespace=june-services \
    --dry-run=client -o yaml | kubectl apply -f -

log_success "Application secrets created!"

# ============================================================================
# STEP 10: UPDATE MANIFESTS
# ============================================================================

log_step "Step 10: Configuring deployment manifests..."

# Load networking config if available
if [ -f "$CONFIG_DIR/networking.env" ]; then
    source "$CONFIG_DIR/networking.env"
fi

# Create updated complete-manifests.yaml
if [ -f "$SCRIPT_DIR/../k8s/complete-manifests.yaml" ]; then
    log_info "Creating customized manifests for your domain..."
    
    CUSTOM_MANIFEST="$CONFIG_DIR/complete-manifests-${PRIMARY_DOMAIN//./-}.yaml"
    
    # Copy and customize the manifest
    cp "$SCRIPT_DIR/../k8s/complete-manifests.yaml" "$CUSTOM_MANIFEST"
    
    # Replace domains in the manifest
    sed -i "s/api\.allsafe\.world/${API_DOMAIN}/g" "$CUSTOM_MANIFEST"
    sed -i "s/idp\.allsafe\.world/${IDP_DOMAIN}/g" "$CUSTOM_MANIFEST"
    sed -i "s/stt\.allsafe\.world/${STT_DOMAIN}/g" "$CUSTOM_MANIFEST"
    sed -i "s/tts\.allsafe\.world/${TTS_DOMAIN}/g" "$CUSTOM_MANIFEST"
    sed -i "s/\*\.allsafe\.world/\*.${PRIMARY_DOMAIN}/g" "$CUSTOM_MANIFEST"
    sed -i "s/allsafe-wildcard-tls/${CERT_SECRET_NAME}/g" "$CUSTOM_MANIFEST"
    
    log_success "Custom manifest created: $CUSTOM_MANIFEST"
else
    log_warning "complete-manifests.yaml not found, skipping manifest customization"
fi

# ============================================================================
# FINAL SUMMARY
# ============================================================================

EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo "══════════════════════════════════════════════════"
log_success "🎉 June Platform Installation Complete!"
echo "══════════════════════════════════════════════════"
echo ""
echo "✅ Installed Components:"
echo "  • Core Infrastructure (K8s, ingress-nginx, cert-manager)"
echo "  • Networking (MetalLB, STUNner with Gateway API v1alpha2)"
if [[ $INSTALL_GPU =~ ^[Yy]$ ]]; then
    echo "  • GPU Operator with time-slicing"
fi
if [[ $INSTALL_RUNNER =~ ^[Yy]$ ]]; then
    echo "  • GitHub Actions Runner"
fi
echo "  • Let's Encrypt ClusterIssuer"
echo "  • SSL Certificate for ${PRIMARY_DOMAIN}"
echo "  • Application secrets"
echo ""
echo "🌍 Cluster Information:"
echo "  External IP: $EXTERNAL_IP"
echo "  Namespace: june-services"
echo ""
echo "🌐 Your Domains:"
echo "  Primary: ${PRIMARY_DOMAIN}"
echo "  API: ${API_DOMAIN}"
echo "  Identity: ${IDP_DOMAIN}"
echo "  Speech-to-Text: ${STT_DOMAIN}"
echo "  Text-to-Speech: ${TTS_DOMAIN}"
echo "  Certificate: ${CERT_SECRET_NAME}"
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
echo "  All configs: $CONFIG_DIR/"
if [ -f "$CUSTOM_MANIFEST" ]; then
    echo "  Custom manifest: $CUSTOM_MANIFEST"
fi
echo ""
echo "📋 Next Steps:"
echo ""
echo "1. 🌐 Configure DNS records to point to $EXTERNAL_IP:"
echo "   ${PRIMARY_DOMAIN} A $EXTERNAL_IP"
echo "   *.${PRIMARY_DOMAIN} A $EXTERNAL_IP"
echo ""
echo "2. 🔍 Verify certificate status:"
echo "   kubectl get certificate $CERT_SECRET_NAME -n june-services"
echo "   kubectl describe certificate $CERT_SECRET_NAME -n june-services"
echo ""
echo "3. 🚀 Deploy June services:"
if [ -f "$CUSTOM_MANIFEST" ]; then
    echo "   kubectl apply -f $CUSTOM_MANIFEST"
else
    echo "   kubectl apply -f k8s/complete-manifests.yaml"
fi
echo ""
echo "4. 📊 Monitor deployment:"
echo "   kubectl get pods -n june-services -w"
echo ""
echo "5. 🔗 Test your services:"
echo "   curl https://${API_DOMAIN}/healthz"
echo "   curl https://${IDP_DOMAIN}/health"
echo ""
echo "🔍 Useful Commands:"
echo "  # Check certificate status"
echo "  kubectl get certificates -n june-services"
echo "  kubectl get secrets -n june-services | grep tls"
echo ""
echo "  # Check all services"
echo "  kubectl get all -n june-services"
echo ""
echo "  # View service logs"
echo "  kubectl logs -n june-services -l app=june-orchestrator --tail=50"
echo ""
echo "  # Check ingress status"
echo "  kubectl get ingress -n june-services"
echo "  kubectl describe ingress june-ingress -n june-services"
echo ""
echo "══════════════════════════════════════════════════"
echo "🆘 Troubleshooting:"
echo ""
echo "If certificates aren't working:"
echo "  kubectl describe certificate $CERT_SECRET_NAME -n june-services"
echo "  kubectl logs -n cert-manager deployment/cert-manager"
echo ""
echo "If services show temp certificates:"
echo "  kubectl delete certificate $CERT_SECRET_NAME -n june-services"
echo "  kubectl delete secret $CERT_SECRET_NAME -n june-services"
echo "  # Then re-run this script to recreate"
echo ""
echo "══════════════════════════════════════════════════"