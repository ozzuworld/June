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
    
    # Save configuration
cat > "$CONFIG_DIR/infrastructure.env" << EOF
POD_NETWORK_CIDR=$POD_NETWORK_CIDR
LETSENCRYPT_EMAIL=$LETSENCRYPT_EMAIL
CF_API_TOKEN=$CF_API_TOKEN
INSTALL_DATE="$(date -u +\"%Y-%m-%d %H:%M:%S UTC\")"
EOF
    chmod 600 "$CONFIG_DIR/infrastructure.env"
    log_success "Infrastructure config saved"
fi

# ============================================================================
# FIXED: CONSISTENT DOMAIN AND CERTIFICATE CONFIGURATION
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
# FIXED: CONSISTENT CERTIFICATE NAMING STRATEGY
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
    log_warning "You will need to update the ingress manifest to use: $CERT_SECRET_NAME"
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
# DOMAIN VALIDATION AND INGRESS COMPATIBILITY CHECK
# ============================================================================

log_info "🔍 Validating domain compatibility with existing manifests..."

# Check if we need to update the ingress manifest for custom domains
if [ "$PRIMARY_DOMAIN" != "allsafe.world" ]; then
    log_warning "⚠️  DOMAIN MISMATCH DETECTED!"
    log_warning "   Install script domain: $PRIMARY_DOMAIN"
    log_warning "   Ingress manifest expects: allsafe.world"
    echo ""
    log_warning "📝 Action Required:"
    log_warning "   After installation, you must update k8s/complete-manifests.yaml:"
    log_warning "   1. Replace 'allsafe.world' with '$PRIMARY_DOMAIN'"
    log_warning "   2. Replace 'allsafe-wildcard-tls' with '$CERT_SECRET_NAME'"
    echo ""
    
    read -p "Do you want to continue with domain '$PRIMARY_DOMAIN'? [y/N]: " CONTINUE_CUSTOM
    if [[ ! "$CONTINUE_CUSTOM" =~ ^[Yy]$ ]]; then
        log_error "Installation cancelled. Please reconfigure with allsafe.world or update manifests."
        exit 1
    fi
else
    log_success "Domain configuration matches existing ingress manifests"
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
# IMPROVED CERTIFICATE MANAGEMENT
# ============================================================================

log_info "🔐 Certificate Management: Advanced backup detection and validation..."

CERT_BACKUP_DIR="/root/.june-certs"
CERT_RESTORED=false

# Ensure june-services namespace exists
kubectl create namespace june-services || true

# ============================================================================
# ENHANCED CERTIFICATE BACKUP DETECTION
# ============================================================================

if [ -d "$CERT_BACKUP_DIR" ]; then
    log_info "Scanning for certificate backups..."
    
    # Look for multiple backup patterns
    CERT_BACKUPS=(
        $(find "$CERT_BACKUP_DIR" -name "*wildcard*tls*.yaml" -type f 2>/dev/null)
        $(find "$CERT_BACKUP_DIR" -name "*${CERT_SECRET_NAME}*.yaml" -type f 2>/dev/null)
        $(find "$CERT_BACKUP_DIR" -name "allsafe*.yaml" -type f 2>/dev/null)
    )
    
    # Remove duplicates and pick the most recent
    if [ ${#CERT_BACKUPS[@]} -gt 0 ]; then
        CERT_BACKUP=$(printf '%s\n' "${CERT_BACKUPS[@]}" | sort -u | head -1)
        
        if [ -n "$CERT_BACKUP" ] && [ -f "$CERT_BACKUP" ]; then
            log_info "Found certificate backup: $CERT_BACKUP"
            
            # Enhanced backup validation
            if grep -q "kind: Secret" "$CERT_BACKUP" && grep -q "tls.crt" "$CERT_BACKUP" && grep -q "tls.key" "$CERT_BACKUP"; then
                log_success "Backup file structure is valid"
                
                # Extract and validate certificate domains
                BACKUP_SECRET_NAME=$(grep -A1 "kind: Secret" "$CERT_BACKUP" | grep "name:" | head -1 | awk '{print $2}')
                
                if [ -n "$BACKUP_SECRET_NAME" ]; then
                    log_info "Backup contains certificate: $BACKUP_SECRET_NAME"
                    
                    # Apply the backup
                    kubectl apply -f "$CERT_BACKUP" 2>/dev/null || {
                        log_warning "Failed to apply backup, trying with different namespace..."
                        # Try copying to current namespace
                        sed "s/namespace:.*/namespace: june-services/g" "$CERT_BACKUP" | kubectl apply -f - 2>/dev/null || {
                            log_error "Could not restore certificate backup"
                        }
                    }
                    
                    sleep 3
                    
                    # Verify restoration
                    if kubectl get secret "$BACKUP_SECRET_NAME" -n june-services &>/dev/null; then
                        log_success "Certificate restored from backup: $BACKUP_SECRET_NAME"
                        
                        # Enhanced certificate validation
                        validate_certificate_backup() {
                            local secret_name="$1"
                            
                            # Extract certificate data
                            local cert_data=$(kubectl get secret "$secret_name" -n june-services -o jsonpath='{.data.tls\.crt}' 2>/dev/null)
                            
                            if [ -n "$cert_data" ]; then
                                # Decode and check certificate
                                echo "$cert_data" | base64 -d > /tmp/cert_check.crt 2>/dev/null || return 1
                                
                                # Check expiration
                                local expiry=$(openssl x509 -in /tmp/cert_check.crt -noout -enddate 2>/dev/null | cut -d= -f2)
                                
                                if [ -n "$expiry" ]; then
                                    log_info "Certificate expires: $expiry"
                                    
                                    local expiry_epoch=$(date -d "$expiry" +%s 2>/dev/null)
                                    local now_epoch=$(date +%s)
                                    local days_left=$(( (expiry_epoch - now_epoch) / 86400 ))
                                    
                                    if [ $days_left -lt 0 ]; then
                                        log_error "Certificate has EXPIRED! Will create new one..."
                                        return 1
                                    elif [ $days_left -lt 30 ]; then
                                        log_warning "Certificate expires in $days_left days - consider renewal"
                                    else
                                        log_success "Certificate is valid ($days_left days remaining)"
                                    fi
                                    
                                    # Check domains
                                    local cert_domains=$(openssl x509 -in /tmp/cert_check.crt -noout -text 2>/dev/null | grep -A1 "Subject Alternative Name" | tail -1 | tr ',' '\n' | grep DNS: | sed 's/.*DNS://' | tr '\n' ' ')
                                    
                                    if [[ "$cert_domains" == *"$PRIMARY_DOMAIN"* ]]; then
                                        log_success "Certificate covers required domain: $PRIMARY_DOMAIN"
                                        return 0
                                    else
                                        log_warning "Certificate domains: $cert_domains"
                                        log_warning "Required domain: $PRIMARY_DOMAIN"
                                        log_warning "Domain mismatch detected"
                                        return 1
                                    fi
                                else
                                    log_warning "Could not parse certificate expiration"
                                    return 1
                                fi
                            else
                                log_error "Could not extract certificate data"
                                return 1
                            fi
                        }
                        
                        if validate_certificate_backup "$BACKUP_SECRET_NAME"; then
                            CERT_RESTORED=true
                            CERT_SECRET_NAME="$BACKUP_SECRET_NAME"
                            
                            # Update config with restored certificate name
                            if grep -q "^CERT_SECRET_NAME=" "$CONFIG_DIR/domain-config.env"; then
                                sed -i "s/^CERT_SECRET_NAME=.*/CERT_SECRET_NAME=$CERT_SECRET_NAME/" "$CONFIG_DIR/domain-config.env"
                            else
                                echo "CERT_SECRET_NAME=$CERT_SECRET_NAME" >> "$CONFIG_DIR/domain-config.env"
                            fi
                            
                            log_success "Certificate backup validation successful"
                        else
                            log_warning "Certificate backup validation failed - will create new certificate"
                            kubectl delete secret "$BACKUP_SECRET_NAME" -n june-services 2>/dev/null || true
                            CERT_RESTORED=false
                        fi
                        
                        # Cleanup
                        rm -f /tmp/cert_check.crt
                    else
                        log_error "Certificate restoration failed - secret not found after restore"
                        CERT_RESTORED=false
                    fi
                else
                    log_error "Could not extract secret name from backup"
                    CERT_RESTORED=false
                fi
            else
                log_error "Backup file is invalid or corrupted (missing required fields)"
                CERT_RESTORED=false
            fi
        else
            log_info "No valid certificate backup files found"
        fi
    else
        log_info "No certificate backup files found in $CERT_BACKUP_DIR"
    fi
else
    log_info "Certificate backup directory does not exist (first-time setup)"
fi

# ============================================================================
# ENHANCED CERTIFICATE CREATION
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
            kubectl describe clusterissuer letsencrypt-prod | tail -10
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
            log_success "✅ Certificate issued successfully!"
            
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
        log_error "❌ Certificate issuance timed out or failed!"
        log_error "Debug information:"
        echo ""
        kubectl describe certificate "${CERT_NAME}" -n june-services | tail -15
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
# GENERATE DYNAMIC MANIFESTS
# ============================================================================

log_info "🔧 Generating dynamic manifests..."

# Create the generate script if it doesn't exist
if [ ! -f "scripts/generate-manifests.sh" ]; then
    log_warning "Manifest generator script not found - manifests will need manual updates"
    MANIFESTS_READY=false
else
    # Make sure script is executable
    chmod +x scripts/generate-manifests.sh
    
    # Generate manifests with current configuration
    if ./scripts/generate-manifests.sh; then
        log_success "✅ Dynamic manifests generated successfully"
        MANIFESTS_READY=true
    else
        log_error "❌ Failed to generate dynamic manifests"
        MANIFESTS_READY=false
    fi
fi


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
    echo "⚠️  IMPORTANT - Custom Domain Configuration:"
    echo "  Before deploying services, update k8s/complete-manifests.yaml:"
    echo "  1. Replace all instances of 'allsafe.world' with '$PRIMARY_DOMAIN'"
    echo "  2. Replace 'allsafe-wildcard-tls' with '$CERT_SECRET_NAME'"
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
if [ "$PRIMARY_DOMAIN" != "allsafe.world" ]; then
    echo "     # First update the manifest for your domain, then:"
fi
echo "     kubectl apply -f k8s/complete-manifests.yaml"
echo ""
echo "  4. Create certificate backup:"
echo "     ./scripts/install-k8s/backup-wildcard-cert.sh"
echo ""
echo "======================================================"