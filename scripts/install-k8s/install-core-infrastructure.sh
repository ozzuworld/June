#!/bin/bash
# Core Infrastructure Setup: K8s + Docker + ingress-nginx + cert-manager
# This is the foundation - run this first
# Usage: ./install-core-infrastructure.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }

echo "======================================================"
echo "🏗️  Core Infrastructure Setup"
echo "   Docker + Kubernetes + Ingress + Cert-Manager"
echo "======================================================"
echo ""

# Configuration
CONFIG_DIR="/root/.june-config"
mkdir -p "$CONFIG_DIR"

# ============================================================================
# FIXED: PROPER PATH DETECTION
# ============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MANIFEST_PATH="$REPO_ROOT/k8s/complete-manifests.yaml"

# ============================================================================
# CONFIGURATION COLLECTION (MOVED TO TOP)
# ============================================================================

log_info "📋 Loading/Collecting Configuration..."

# Load existing configs if available
if [ -f "$CONFIG_DIR/infrastructure.env" ]; then
    log_info "Loading infrastructure config..."
    source "$CONFIG_DIR/infrastructure.env"
fi

if [ -f "$CONFIG_DIR/domain-config.env" ]; then
    log_info "Loading domain config..."
    source "$CONFIG_DIR/domain-config.env"
fi

# Collect missing infrastructure configuration
if [ -z "$POD_NETWORK_CIDR" ] || [ -z "$LETSENCRYPT_EMAIL" ] || [ -z "$CF_API_TOKEN" ]; then
    log_info "Collecting infrastructure configuration..."
    
    read -p "Pod network CIDR [10.244.0.0/16]: " POD_NETWORK_CIDR
    POD_NETWORK_CIDR=${POD_NETWORK_CIDR:-10.244.0.0/16}
    
    read -p "Let's Encrypt email: " LETSENCRYPT_EMAIL
    read -p "Cloudflare API Token: " CF_API_TOKEN
    
    # Save configuration - FIXED DATE FORMAT
cat > "$CONFIG_DIR/infrastructure.env" << EOF
POD_NETWORK_CIDR=$POD_NETWORK_CIDR
LETSENCRYPT_EMAIL=$LETSENCRYPT_EMAIL
CF_API_TOKEN=$CF_API_TOKEN
INSTALL_DATE="$(date -u +"%Y-%m-%d %H:%M:%S UTC")"
EOF
    chmod 600 "$CONFIG_DIR/infrastructure.env"
    log_success "Infrastructure config saved"
fi

# ============================================================================
# ENHANCED DOMAIN AND CERTIFICATE CONFIGURATION
# ============================================================================

# Check if domain config exists and validate consistency
if [ -z "$PRIMARY_DOMAIN" ]; then
    log_info "🔧 Domain Configuration Setup..."
    
    # Default to allsafe.world for consistency with existing manifests
    read -p "Primary domain [allsafe.world]: " PRIMARY_DOMAIN
    PRIMARY_DOMAIN=${PRIMARY_DOMAIN:-allsafe.world}
    
    read -p "API subdomain [api]: " API_SUBDOMAIN
    API_SUBDOMAIN=${API_SUBDOMAIN:-api}
    
    read -p "IDP subdomain [idp]: " IDP_SUBDOMAIN
    IDP_SUBDOMAIN=${IDP_SUBDOMAIN:-idp}
    
    read -p "STT subdomain [stt]: " STT_SUBDOMAIN
    STT_SUBDOMAIN=${STT_SUBDOMAIN:-stt}
    
    read -p "TTS subdomain [tts]: " TTS_SUBDOMAIN
    TTS_SUBDOMAIN=${TTS_SUBDOMAIN:-tts}
    
    DOMAIN_CONFIG_NEW=true
else
    DOMAIN_CONFIG_NEW=false
fi

# Construct full domains
API_DOMAIN="${API_SUBDOMAIN:-api}.${PRIMARY_DOMAIN}"
IDP_DOMAIN="${IDP_SUBDOMAIN:-idp}.${PRIMARY_DOMAIN}"
STT_DOMAIN="${STT_SUBDOMAIN:-stt}.${PRIMARY_DOMAIN}"
TTS_DOMAIN="${TTS_SUBDOMAIN:-tts}.${PRIMARY_DOMAIN}"
WILDCARD_DOMAIN="*.${PRIMARY_DOMAIN}"

# ============================================================================
# CONSISTENT CERTIFICATE NAMING STRATEGY
# ============================================================================

# Use consistent certificate naming that matches existing ingress expectations
if [ "$PRIMARY_DOMAIN" = "allsafe.world" ]; then
    # Use the exact naming expected by the ingress manifest
    CERT_NAME="allsafe-wildcard"
    CERT_SECRET_NAME="allsafe-wildcard-tls"
    log_info "Using standard certificate naming for allsafe.world domain"
else
    # Generate certificate name for custom domains
    CERT_NAME="${PRIMARY_DOMAIN//./-}-wildcard"
    CERT_SECRET_NAME="${CERT_NAME}-tls"
    log_warning "Custom domain detected: $PRIMARY_DOMAIN"
fi

# Save or update domain configuration
cat > "$CONFIG_DIR/domain-config.env" << EOF
PRIMARY_DOMAIN=$PRIMARY_DOMAIN
API_SUBDOMAIN=${API_SUBDOMAIN:-api}
IDP_SUBDOMAIN=${IDP_SUBDOMAIN:-idp}
STT_SUBDOMAIN=${STT_SUBDOMAIN:-stt}
TTS_SUBDOMAIN=${TTS_SUBDOMAIN:-tts}
API_DOMAIN=$API_DOMAIN
IDP_DOMAIN=$IDP_DOMAIN
STT_DOMAIN=$STT_DOMAIN
TTS_DOMAIN=$TTS_DOMAIN
WILDCARD_DOMAIN=$WILDCARD_DOMAIN
CERT_NAME=$CERT_NAME
CERT_SECRET_NAME=$CERT_SECRET_NAME
EOF
chmod 600 "$CONFIG_DIR/domain-config.env"

if [ "$DOMAIN_CONFIG_NEW" = true ]; then
    log_success "Domain configuration saved"
else
    log_success "Domain configuration updated"
fi

# Display summary
echo ""
log_info "🔧 Configuration Summary:"
echo "  Pod Network: $POD_NETWORK_CIDR"
echo "  Primary Domain: $PRIMARY_DOMAIN"
echo "  API Domain: $API_DOMAIN"
echo "  IDP Domain: $IDP_DOMAIN"
echo "  Certificate Name: $CERT_NAME"
echo "  Certificate Secret: $CERT_SECRET_NAME"
echo "  Email: $LETSENCRYPT_EMAIL"
echo ""

# ============================================================================
# CERTIFICATE RESTORE OPTION DURING SETUP
# ============================================================================

log_info "🔐 Certificate Management Options..."

CERT_BACKUP_DIR="/root/.june-certs"
CERT_RESTORE_CHOICE=false
SELECTED_CERT_BACKUP=""

# Check for existing certificates first
if [ -d "$CERT_BACKUP_DIR" ]; then
    # Look for certificate backups
    AVAILABLE_BACKUPS=($(find "$CERT_BACKUP_DIR" -name "*wildcard*tls*.yaml" -o -name "*${CERT_SECRET_NAME}*.yaml" -o -name "allsafe*.yaml" 2>/dev/null | head -5))
    
    if [ ${#AVAILABLE_BACKUPS[@]} -gt 0 ]; then
        echo ""
        log_info "🔍 Found existing certificate backups:"
        for i in "${!AVAILABLE_BACKUPS[@]}"; do
            BACKUP_FILE="${AVAILABLE_BACKUPS[$i]}"
            BACKUP_DATE=$(stat -c %y "$BACKUP_FILE" 2>/dev/null | cut -d' ' -f1 || echo "unknown")
            BACKUP_NAME=$(basename "$BACKUP_FILE" .yaml)
            echo "  $((i+1)). $BACKUP_NAME (from $BACKUP_DATE)"
        done
        echo "  $((${#AVAILABLE_BACKUPS[@]}+1)). Create new certificate with Let's Encrypt"
        echo ""
        
        read -p "Choose certificate option [1-$((${#AVAILABLE_BACKUPS[@]}+1))]: " CERT_CHOICE
        
        if [[ "$CERT_CHOICE" -ge 1 && "$CERT_CHOICE" -le "${#AVAILABLE_BACKUPS[@]}" ]]; then
            SELECTED_CERT_BACKUP="${AVAILABLE_BACKUPS[$((CERT_CHOICE-1))]}"
            log_info "Selected backup: $(basename "$SELECTED_CERT_BACKUP")"
            
            # Validate the selected backup
            if grep -q "kind: Secret" "$SELECTED_CERT_BACKUP" && grep -q "tls.crt" "$SELECTED_CERT_BACKUP"; then
                log_success "✅ ✅ Backup file is valid"
                CERT_RESTORE_CHOICE=true
            else
                log_error "❌ ❌ Invalid backup file structure"
                log_info "Will create new certificate instead"
            fi
        else
            log_info "Will create new certificate with Let's Encrypt"
        fi
    else
        log_info "No certificate backups found - will create new certificate"
    fi
else
    log_info "No certificate backup directory found - first time setup"
fi

# ============================================================================
# ENHANCED DOMAIN VALIDATION WITH AUTOMATIC FIXES - COMPLETELY FIXED
# ============================================================================

log_info "🔍 Validating domain compatibility with existing manifests..."

# Check if we need to update the ingress manifest for custom domains
if [ "$PRIMARY_DOMAIN" != "allsafe.world" ]; then
    log_warning "⚠️  ⚠️  DOMAIN MISMATCH DETECTED!"
    log_warning "   Install script domain: $PRIMARY_DOMAIN"
    log_warning "   Ingress manifest expects: allsafe.world"
    echo ""
    echo "Options:"
    echo "1. 🔄 Automatically update manifests to use $PRIMARY_DOMAIN"
    echo "2. 🏠 Switch back to allsafe.world (recommended)"
    echo "3. ⚠️  Continue with manual updates required"
    echo "4. ❌ Cancel installation"
    echo ""
    read -p "Choose option [1-4]: " DOMAIN_OPTION
    
    case $DOMAIN_OPTION in
        1)
            log_info "🔄 Automatically updating manifests for $PRIMARY_DOMAIN..."
            
            # FIXED: Use proper path detection and consistent file operations
            if [ -f "$MANIFEST_PATH" ]; then
                # Create backup with timestamp using full path
                BACKUP_FILE="${MANIFEST_PATH}.backup-$(date +%Y%m%d-%H%M%S)"
                cp "$MANIFEST_PATH" "$BACKUP_FILE"
                
                # Update domains and certificate names in the actual manifest file
                sed -i "s/allsafe\.world/$PRIMARY_DOMAIN/g" "$MANIFEST_PATH"
                sed -i "s/allsafe-wildcard-tls/$CERT_SECRET_NAME/g" "$MANIFEST_PATH"
                
                log_success "✅ ✅ Manifests updated automatically"
                log_info "   Backup saved as: $BACKUP_FILE"
            else
                log_error "❌ ❌ Manifest file not found: $MANIFEST_PATH"
                log_error "   Expected at: $MANIFEST_PATH"
                log_error "   Current directory: $(pwd)"
                log_error "   Script directory: $SCRIPT_DIR"
                log_error "   Repository root: $REPO_ROOT"
                exit 1
            fi
            ;;
        2)
            log_info "🏠 Switching to allsafe.world configuration..."
            PRIMARY_DOMAIN="allsafe.world"
            CERT_NAME="allsafe-wildcard"
            CERT_SECRET_NAME="allsafe-wildcard-tls"
            
            # Update all derived domains
            API_DOMAIN="api.${PRIMARY_DOMAIN}"
            IDP_DOMAIN="idp.${PRIMARY_DOMAIN}"
            STT_DOMAIN="stt.${PRIMARY_DOMAIN}"
            TTS_DOMAIN="tts.${PRIMARY_DOMAIN}"
            WILDCARD_DOMAIN="*.${PRIMARY_DOMAIN}"
            
            log_success "✅ ✅ Switched to standard allsafe.world configuration"
            ;;
        3)
            log_warning "⚠️  ⚠️  Continuing with manual updates required"
            log_warning "   Remember to update $MANIFEST_PATH after installation!"
            ;;
        4)
            log_info "❌ ❌ Installation cancelled by user"
            exit 0
            ;;
        *)
            log_error "❌ ❌ Invalid option selected"
            exit 1
            ;;
    esac
    
    # Update configuration file with final values
    cat > "$CONFIG_DIR/domain-config.env" << EOF
PRIMARY_DOMAIN=$PRIMARY_DOMAIN
API_SUBDOMAIN=${API_SUBDOMAIN:-api}
IDP_SUBDOMAIN=${IDP_SUBDOMAIN:-idp}
STT_SUBDOMAIN=${STT_SUBDOMAIN:-stt}
TTS_SUBDOMAIN=${TTS_SUBDOMAIN:-tts}
API_DOMAIN=$API_DOMAIN
IDP_DOMAIN=$IDP_DOMAIN
STT_DOMAIN=$STT_DOMAIN
TTS_DOMAIN=$TTS_DOMAIN
WILDCARD_DOMAIN=$WILDCARD_DOMAIN
CERT_NAME=$CERT_NAME
CERT_SECRET_NAME=$CERT_SECRET_NAME
EOF
else
    log_success "✅ ✅ Domain configuration matches existing ingress manifests"
fi

# ============================================================================
# DOCKER
# ============================================================================

log_info "🐳 Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io
else
    log_success "Docker already installed"
fi

# Configure containerd
systemctl stop containerd
mkdir -p /etc/containerd
containerd config default > /etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd

log_success "Docker configured!"

# ============================================================================
# KUBERNETES
# ============================================================================

log_info "☸️  Installing Kubernetes..."

# Kernel modules
modprobe br_netfilter
cat <<EOF | tee /etc/modules-load.d/k8s.conf
br_netfilter
EOF

cat <<EOF | tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
EOF
sysctl --system

# Install K8s packages
if ! command -v kubeadm &> /dev/null; then
    rm -f /etc/apt/sources.list.d/kubernetes.list
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
    apt-get update -qq
    apt-get install -y kubelet kubeadm kubectl
    apt-mark hold kubelet kubeadm kubectl
else
    log_success "Kubernetes packages already installed"
fi

# Initialize cluster if not already done
if [ ! -f /etc/kubernetes/admin.conf ]; then
    log_info "Initializing Kubernetes cluster..."
    INTERNAL_IP=$(hostname -I | awk '{print $1}')
    kubeadm init --pod-network-cidr=$POD_NETWORK_CIDR --apiserver-advertise-address=$INTERNAL_IP --cri-socket=unix:///var/run/containerd/containerd.sock
    
    mkdir -p /root/.kube
    cp /etc/kubernetes/admin.conf /root/.kube/config
    chown root:root /root/.kube/config
else
    log_success "Kubernetes already initialized"
fi

# Install Flannel
log_info "Installing Flannel network..."
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

# Remove taints
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl taint nodes --all node-role.kubernetes.io/master- || true

# Wait for cluster
kubectl wait --for=condition=Ready nodes --all --timeout=300s

log_success "Kubernetes cluster ready!"

# ============================================================================
# INGRESS-NGINX
# ============================================================================

log_info "🌐 Installing ingress-nginx..."
if ! kubectl get namespace ingress-nginx &>/dev/null; then
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml
    sleep 15
    
    # Enable hostNetwork
    log_info "Enabling hostNetwork mode..."
    kubectl patch deployment ingress-nginx-controller \
        -n ingress-nginx \
        --type='json' \
        -p='[
            {"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},
            {"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}
        ]'
    
    # Wait for rollout
    log_info "Waiting for ingress controller rollout..."
    kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=300s
else
    log_success "ingress-nginx already installed"
fi

# Verify
log_info "Verifying ingress controller..."
kubectl wait --namespace ingress-nginx \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=120s 2>/dev/null || {
    log_warning "Wait timed out, checking status..."
    kubectl get pods -n ingress-nginx -l app.kubernetes.io/component=controller
}

log_success "ingress-nginx ready!"

# ============================================================================
# CERT-MANAGER
# ============================================================================

log_info "🔐 Installing cert-manager..."
if ! kubectl get namespace cert-manager &>/dev/null; then
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.crds.yaml
    kubectl create namespace cert-manager
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.yaml
    
    log_info "Waiting for cert-manager to be ready..."
    kubectl wait --for=condition=ready pod \
        -l app.kubernetes.io/instance=cert-manager \
        -n cert-manager \
        --timeout=180s
else
    log_success "cert-manager already installed"
fi

# Verify cert-manager is actually ready
log_info "Verifying cert-manager readiness..."
kubectl wait --for=condition=Available deployment/cert-manager -n cert-manager --timeout=60s
kubectl wait --for=condition=Available deployment/cert-manager-webhook -n cert-manager --timeout=60s
kubectl wait --for=condition=Available deployment/cert-manager-cainjector -n cert-manager --timeout=60s

# Create Cloudflare secret
log_info "Creating Cloudflare API token secret..."
kubectl create secret generic cloudflare-api-token \
    --from-literal=api-token="$CF_API_TOKEN" \
    --namespace=cert-manager \
    --dry-run=client -o yaml | kubectl apply -f -

log_success "cert-manager ready!"

# ============================================================================
# IMPROVED CERTIFICATE MANAGEMENT WITH FIXED VALIDATION
# ============================================================================

log_info "🔐 Processing Certificate Configuration..."

# Ensure june-services namespace exists
kubectl create namespace june-services || true

CERT_RESTORED=false

# FIXED: Certificate validation function with retry logic
validate_restored_certificate() {
    local expected_secret_name="$1"
    local max_attempts=30
    local attempt=1
    
    log_info "Validating certificate restoration (max ${max_attempts}s)..."
    
    while [ $attempt -le $max_attempts ]; do
        # Check if the expected secret exists
        if kubectl get secret "$expected_secret_name" -n june-services >/dev/null 2>&1; then
            log_success "Certificate secret '$expected_secret_name' found in namespace 'june-services'"
            
            # Additional validation - check if it contains certificate data
            local cert_data=$(kubectl get secret "$expected_secret_name" -n june-services -o jsonpath='{.data.tls\.crt}' 2>/dev/null || echo "")
            if [ -n "$cert_data" ] && [ "$cert_data" != "null" ]; then
                log_success "Certificate contains valid TLS data"
                return 0
            else
                log_warning "Certificate secret exists but missing TLS data"
            fi
        fi
        
        if [ $attempt -le 5 ]; then
            log_info "Attempt $attempt/$max_attempts - waiting for secret..."
        elif [ $((attempt % 5)) -eq 0 ]; then
            log_info "Still waiting... ($attempt/$max_attempts attempts)"
        fi
        
        sleep 1
        ((attempt++))
    done
    
    log_error "Certificate validation failed after $max_attempts attempts"
    log_info "Checking what certificates exist:"
    kubectl get secrets -n june-services | grep -E "(tls|cert)" || echo "No TLS secrets found"
    return 1
}

# Handle certificate restoration if user chose it during setup
if [ "$CERT_RESTORE_CHOICE" = true ] && [ -n "$SELECTED_CERT_BACKUP" ]; then
    log_info "🔄 Restoring selected certificate backup..."
    
    # FIXED: Better secret name extraction from backup
    # Try multiple methods to get the actual Kubernetes secret name
    BACKUP_SECRET_NAME=""
    
    # Method 1: Look for metadata.name in YAML
    BACKUP_SECRET_NAME=$(grep -A1 "^metadata:" "$SELECTED_CERT_BACKUP" | grep "name:" | awk '{print $2}' | tr -d '"' | head -1)
    
    # Method 2: If that fails, try direct name field
    if [ -z "$BACKUP_SECRET_NAME" ]; then
        BACKUP_SECRET_NAME=$(grep "^[[:space:]]*name:" "$SELECTED_CERT_BACKUP" | grep -v "certificate-name" | head -1 | awk '{print $2}' | tr -d '"')
    fi
    
    # Method 3: Use filename as fallback
    if [ -z "$BACKUP_SECRET_NAME" ]; then
        BACKUP_SECRET_NAME=$(basename "$SELECTED_CERT_BACKUP" .yaml | sed 's/-backup$//')
    fi
    
    if [ -n "$BACKUP_SECRET_NAME" ]; then
        log_info "Restoring certificate secret: $BACKUP_SECRET_NAME"
        
        # Create a temporary file with the correct namespace
        TEMP_RESTORE_FILE="/tmp/cert_restore_$(date +%s).yaml"
        
        # Update namespace in backup and apply
        sed "s/namespace:.*/namespace: june-services/g" "$SELECTED_CERT_BACKUP" > "$TEMP_RESTORE_FILE"
        
        if kubectl apply -f "$TEMP_RESTORE_FILE" 2>/dev/null; then
            rm -f "$TEMP_RESTORE_FILE"
            
            # FIXED: Use improved validation function
            if validate_restored_certificate "$BACKUP_SECRET_NAME"; then
                log_success "✅ Certificate restored successfully: $BACKUP_SECRET_NAME"
                
                # Update certificate secret name in config
                CERT_SECRET_NAME="$BACKUP_SECRET_NAME"
                CERT_RESTORED=true
                
                # Update config file with restored certificate name
                sed -i "s/^CERT_SECRET_NAME=.*/CERT_SECRET_NAME=$CERT_SECRET_NAME/" "$CONFIG_DIR/domain-config.env" 2>/dev/null || {
                    echo "CERT_SECRET_NAME=$CERT_SECRET_NAME" >> "$CONFIG_DIR/domain-config.env"
                }
                
                # Optional: Validate certificate expiry and domains
                CERT_DATA=$(kubectl get secret "$CERT_SECRET_NAME" -n june-services -o jsonpath='{.data.tls\.crt}' | base64 -d 2>/dev/null || echo "")
                if [ -n "$CERT_DATA" ]; then
                    EXPIRY=$(echo "$CERT_DATA" | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || echo "unknown")
                    CERT_DOMAINS=$(echo "$CERT_DATA" | openssl x509 -noout -text 2>/dev/null | grep -A1 "Subject Alternative Name" | tail -1 | tr ',' '\n' | grep DNS: | sed 's/.*DNS://' | tr '\n' ' ' || echo "unknown")
                    
                    log_info "Certificate Details:"
                    echo "  Domains: $CERT_DOMAINS"
                    echo "  Expires: $EXPIRY"
                fi
            else
                log_error "Certificate validation failed"
                CERT_RESTORED=false
            fi
        else
            rm -f "$TEMP_RESTORE_FILE"
            log_error "Failed to apply certificate backup"
            CERT_RESTORED=false
        fi
    else
        log_error "❌ ❌ Could not extract certificate name from backup"
        CERT_RESTORED=false
    fi
fi

# ============================================================================
# ENHANCED CERTIFICATE CREATION (IF NOT RESTORED)
# ============================================================================

if [ "$CERT_RESTORED" = false ]; then
    log_info "🔐 Creating new Certificate resource..."
    
    # Verify prerequisites
    if [ -z "$PRIMARY_DOMAIN" ]; then
        log_error "PRIMARY_DOMAIN is not set! Cannot create certificate."
        exit 1
    fi
    
    log_info "Certificate configuration:"
    echo "  Domain: $PRIMARY_DOMAIN"
    echo "  Certificate name: $CERT_NAME"
    echo "  Secret name: $CERT_SECRET_NAME"
    echo "  Email: $LETSENCRYPT_EMAIL"
    
    # Verify cert-manager is ready
    log_info "Verifying cert-manager readiness before creating certificate..."
    if ! kubectl get crd certificates.cert-manager.io &>/dev/null; then
        log_error "cert-manager CRDs not found! Please wait for cert-manager to be fully ready."
        exit 1
    fi
    
    # Create ClusterIssuer with validation
    log_info "Creating ClusterIssuer..."
    
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
    
    # Wait for ClusterIssuer to be ready
    log_info "Waiting for ClusterIssuer to be ready..."
    sleep 10
    
    # Verify ClusterIssuer
    for i in {1..30}; do
        ISSUER_READY=$(kubectl get clusterissuer letsencrypt-prod -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "False")
        if [ "$ISSUER_READY" = "True" ]; then
            log_success "ClusterIssuer is ready"
            break
        fi
        
        if [ $i -eq 30 ]; then
            log_warning "ClusterIssuer not ready yet, but proceeding..."
            kubectl describe clusterissuer letsencrypt-prod | tail -10 || true
        fi
        
        sleep 2
    done
    
    # Create Certificate resource
    log_info "Creating Certificate resource..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: ${CERT_NAME}
  namespace: june-services
spec:
  secretName: ${CERT_SECRET_NAME}
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: "${PRIMARY_DOMAIN}"
  dnsNames:
  - "${PRIMARY_DOMAIN}"
  - "*.${PRIMARY_DOMAIN}"
EOF
    
    log_success "Certificate resource created"
    log_warning "⏳ Waiting for cert-manager to issue certificate..."
    log_info "This can take 2-10 minutes depending on DNS propagation"
    
    # Enhanced certificate waiting with better feedback
    CERT_WAIT_COUNT=0
    MAX_CERT_WAIT=120  # 10 minutes
    
    while [ $CERT_WAIT_COUNT -lt $MAX_CERT_WAIT ]; do
        CERT_READY=$(kubectl get certificate "${CERT_NAME}" -n june-services -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "False")
        
        if [ "$CERT_READY" = "True" ]; then
            log_success "✅ ✅ Certificate issued successfully!"
            
            # Verify the secret was created
            if kubectl get secret "${CERT_SECRET_NAME}" -n june-services &>/dev/null; then
                log_success "Certificate secret is available: ${CERT_SECRET_NAME}"
                
                # Quick validation of the issued certificate
                CERT_DOMAINS=$(kubectl get secret "${CERT_SECRET_NAME}" -n june-services -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -text 2>/dev/null | grep -A1 "Subject Alternative Name" | tail -1 | tr ',' '\n' | grep DNS: | head -2 | sed 's/.*DNS://' | tr '\n' ' ' || echo "unknown")
                log_success "Certificate covers domains: $CERT_DOMAINS"
            else
                log_error "Certificate secret not found after successful issuance!"
            fi
            
            break
        fi
        
        # Show progress every 15 seconds
        if [ $((CERT_WAIT_COUNT % 15)) -eq 0 ] && [ $CERT_WAIT_COUNT -gt 0 ]; then
            log_info "Still waiting for certificate... (${CERT_WAIT_COUNT}/${MAX_CERT_WAIT}s)"
            
            # Show certificate status for debugging
            CERT_STATUS=$(kubectl get certificate "${CERT_NAME}" -n june-services -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}' 2>/dev/null || echo "No status available")
            if [ "$CERT_STATUS" != "No status available" ] && [ -n "$CERT_STATUS" ]; then
                log_info "Certificate status: $CERT_STATUS"
            fi
        fi
        
        sleep 5
        ((CERT_WAIT_COUNT+=5))
    done
    
    # Final check
    if [ "$CERT_READY" != "True" ]; then
        log_error "❌ ❌ Certificate issuance timed out or failed!"
        log_error "Debug information:"
        echo ""
        kubectl describe certificate "${CERT_NAME}" -n june-services | tail -15 || true
        echo ""
        log_error "Please check:"
        log_error "1. Cloudflare API token has DNS:Edit permissions"
        log_error "2. Domain $PRIMARY_DOMAIN is configured in Cloudflare"
        log_error "3. DNS is properly configured"
        log_warning "You can continue with installation and fix certificates later"
    else
        log_success "🎉 Certificate management complete!"
        log_info "📋 Certificate Summary:"
        echo "  Domain: $PRIMARY_DOMAIN"
        echo "  Certificate: $CERT_NAME"
        echo "  Secret: $CERT_SECRET_NAME"
        echo "  Namespace: june-services"
    fi
else
    log_success "Certificate management complete (restored from backup)!"
fi

log_success "Using certificate secret: ${CERT_SECRET_NAME}"

# ============================================================================
# STORAGE SETUP
# ============================================================================

log_info "📁 Setting up storage infrastructure..."

# Create storage directories
STORAGE_DIRS=(
    "/opt/june-postgresql-data"
    "/opt/june-data"
)

for dir in "${STORAGE_DIRS[@]}"; do
    mkdir -p "$dir"
    chmod 755 "$dir"
done

# Create StorageClass
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-storage
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
EOF

# Create PostgreSQL PV
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: postgresql-pv
  labels:
    type: local
    app: postgresql
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-storage
  local:
    path: /opt/june-postgresql-data
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - $(hostname)
EOF

log_success "Storage infrastructure ready!"

# ============================================================================
# FINAL VALIDATION AND SUMMARY
# ============================================================================

EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ || hostname -I | awk '{print $1}')

echo ""
echo "======================================================"
log_success "🎉 Core Infrastructure Ready!"
echo "======================================================"
echo ""
echo "✅ Installed Components:"
echo "  • Docker + containerd"
echo "  • Kubernetes 1.28 cluster"
echo "  • Flannel networking ($POD_NETWORK_CIDR)"
echo "  • ingress-nginx (hostNetwork mode)"
echo "  • cert-manager with Cloudflare DNS"
echo "  • Local storage infrastructure"
echo ""
echo "🌍 Cluster Configuration:"
echo "  External IP: $EXTERNAL_IP"
echo "  Primary Domain: $PRIMARY_DOMAIN"
echo "  Certificate Secret: $CERT_SECRET_NAME"
echo "  Namespace: june-services"
echo ""
echo "🔐 Certificate Status:"
if [ "$CERT_RESTORED" = true ]; then
    echo "  Status: ✅ Restored from backup"
else
    CERT_CHECK=$(kubectl get certificate "${CERT_NAME}" -n june-services -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
    if [ "$CERT_CHECK" = "True" ]; then
        echo "  Status: ✅ Successfully issued"
    else
        echo "  Status: ⚠️  Check required (see above)"
    fi
fi
echo ""

# Domain compatibility check
if [ "$PRIMARY_DOMAIN" != "allsafe.world" ]; then
    echo "✅ DOMAIN CONFIGURATION:"
    echo "  Your manifests have been updated for '$PRIMARY_DOMAIN'"
    echo "  Certificate secret: '$CERT_SECRET_NAME'"
    echo ""
fi

echo "📝 Next Steps:"
echo "  1. Install MetalLB + STUNner:"
echo "     ./install-networking.sh"
echo ""
echo "  2. Install GPU Operator (optional):"
echo "     ./install-gpu-operator.sh"
echo ""
echo "  3. Deploy June services:"
echo "     kubectl apply -f k8s/complete-manifests.yaml"
echo ""
echo "  4. Create certificate backup:"
echo "     ./scripts/install-k8s/backup-restore-cert.sh backup"
echo ""
echo "======================================================"