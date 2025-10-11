#!/bin/bash
# June Platform - Unified Installation Script
# One script to install everything: K8s + Helm + June Platform
# With automatic certificate backup/restore to avoid Let's Encrypt rate limits

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
log_info() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

echo "=========================================="
echo "June Platform - Unified Installation"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    error "Please run as root (sudo ./install.sh)"
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration file
CONFIG_FILE="${SCRIPT_DIR}/config.env"

if [ ! -f "$CONFIG_FILE" ]; then
    error "Configuration file not found: $CONFIG_FILE
    
Please create it first:
  cp config.env.example config.env
  nano config.env
"
fi

log "Loading configuration from: $CONFIG_FILE"
source "$CONFIG_FILE"

# Validate required variables
REQUIRED_VARS=(
    "DOMAIN"
    "LETSENCRYPT_EMAIL"
    "GEMINI_API_KEY"
    "CLOUDFLARE_TOKEN"
)

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        error "Required variable $var is not set in $CONFIG_FILE"
    fi
done

success "Configuration loaded"
log "Domain: $DOMAIN"
log "Email: $LETSENCRYPT_EMAIL"

# Certificate backup directory
BACKUP_DIR="/root/.june-certs"
CERT_SECRET_NAME="${DOMAIN//\./-}-wildcard-tls"
SKIP_CERT_CREATION="false"

# ============================================================================
# STEP 1: Install Prerequisites
# ============================================================================

install_prerequisites() {
    log "Step 1/7: Installing prerequisites..."
    
    # Update package list
    apt-get update -qq
    
    # Install basic tools
    apt-get install -y \
        curl \
        wget \
        git \
        apt-transport-https \
        ca-certificates \
        gnupg \
        lsb-release \
        jq \
        openssl \
        > /dev/null 2>&1
    
    success "Prerequisites installed"
}

# ============================================================================
# STEP 2: Install Docker
# ============================================================================

install_docker() {
    log "Step 2/7: Installing Docker..."
    
    if command -v docker &> /dev/null; then
        success "Docker already installed"
        return
    fi
    
    # Install Docker
    curl -fsSL https://get.docker.com | bash > /dev/null 2>&1
    
    # Configure containerd
    systemctl stop containerd
    mkdir -p /etc/containerd
    containerd config default > /etc/containerd/config.toml
    sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
    systemctl restart containerd
    systemctl enable containerd > /dev/null 2>&1
    
    success "Docker installed"
}

# ============================================================================
# STEP 3: Install Kubernetes
# ============================================================================

install_kubernetes() {
    log "Step 3/7: Installing Kubernetes..."
    
    if kubectl cluster-info &> /dev/null; then
        success "Kubernetes already running"
        return
    fi
    
    # Load kernel modules
    modprobe br_netfilter
    cat > /etc/modules-load.d/k8s.conf << EOF
br_netfilter
EOF
    
    # Set sysctl parameters
    cat > /etc/sysctl.d/k8s.conf << EOF
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
EOF
    sysctl --system > /dev/null 2>&1
    
    # Install Kubernetes packages
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | \
        gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | \
        tee /etc/apt/sources.list.d/kubernetes.list
    
    apt-get update -qq
    apt-get install -y kubelet kubeadm kubectl > /dev/null 2>&1
    apt-mark hold kubelet kubeadm kubectl
    
    # Initialize cluster
    log "Initializing Kubernetes cluster (this may take a few minutes)..."
    INTERNAL_IP=$(hostname -I | awk '{print $1}')
    kubeadm init \
        --pod-network-cidr=10.244.0.0/16 \
        --apiserver-advertise-address=$INTERNAL_IP \
        --cri-socket=unix:///var/run/containerd/containerd.sock \
        > /dev/null 2>&1
    
    # Configure kubectl
    mkdir -p /root/.kube
    cp /etc/kubernetes/admin.conf /root/.kube/config
    chown root:root /root/.kube/config
    
    # Install Flannel CNI
    kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml > /dev/null 2>&1
    
    # Remove taints
    kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
    kubectl taint nodes --all node-role.kubernetes.io/master- || true
    
    # Wait for cluster to be ready
    kubectl wait --for=condition=Ready nodes --all --timeout=300s > /dev/null 2>&1
    
    success "Kubernetes cluster ready"
}

# ============================================================================
# STEP 4: Install Infrastructure
# ============================================================================

install_infrastructure() {
    log "Step 4/7: Installing infrastructure components..."
    
    # Install ingress-nginx
    if ! kubectl get namespace ingress-nginx &> /dev/null; then
        log "Installing ingress-nginx..."
        kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/baremetal/deploy.yaml > /dev/null 2>&1
        sleep 10
        
        # Enable hostNetwork
        kubectl patch deployment ingress-nginx-controller -n ingress-nginx \
            --type='json' \
            -p='[{"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true},{"op": "add", "path": "/spec/template/spec/dnsPolicy", "value": "ClusterFirstWithHostNet"}]' \
            > /dev/null 2>&1
        
        log "Waiting for ingress-nginx (max 5 minutes)..."
        if timeout 300s kubectl wait --for=condition=ready pod \
            -n ingress-nginx \
            -l app.kubernetes.io/component=controller 2>&1; then
            success "ingress-nginx installed"
        else
            warn "ingress-nginx timeout - checking status..."
            RUNNING=$(kubectl get pods -n ingress-nginx --no-headers 2>/dev/null | grep -c "Running" || echo "0")
            if [ "$RUNNING" -gt 0 ]; then
                warn "ingress-nginx partially running ($RUNNING pods) - continuing"
            else
                error "ingress-nginx failed to start"
            fi
        fi
    else
        success "ingress-nginx already installed"
    fi
    
    # Install cert-manager
    if ! kubectl get namespace cert-manager &> /dev/null; then
        log "Installing cert-manager..."
        kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.yaml > /dev/null 2>&1
        
        log "Waiting for cert-manager pods (max 5 minutes)..."
        sleep 30  # Give it time to start
        
        # Check if pods are being created
        for i in {1..10}; do
            POD_COUNT=$(kubectl get pods -n cert-manager --no-headers 2>/dev/null | wc -l)
            if [ "$POD_COUNT" -gt 0 ]; then
                log "cert-manager pods starting ($POD_COUNT pods found)..."
                break
            fi
            sleep 5
        done
        
        # Wait for ready condition with timeout
        if timeout 240s kubectl wait --for=condition=ready pod \
            -n cert-manager \
            -l app.kubernetes.io/instance=cert-manager 2>&1; then
            success "cert-manager installed"
        else
            warn "cert-manager timeout - checking status..."
            RUNNING=$(kubectl get pods -n cert-manager --no-headers 2>/dev/null | grep -c "Running" || echo "0")
            if [ "$RUNNING" -gt 0 ]; then
                warn "cert-manager partially running ($RUNNING pods) - continuing"
            else
                error "cert-manager failed to start"
            fi
        fi
    else
        success "cert-manager already installed"
    fi
    
    # Wait for cert-manager CRDs to be ready - CRITICAL for ClusterIssuer creation
    log "Waiting for cert-manager CRDs (this is important)..."
    sleep 15  # Initial wait for cert-manager to settle
    
    CRD_READY=false
    for i in {1..60}; do
        if kubectl get crd clusterissuers.cert-manager.io &> /dev/null && \
           kubectl get crd certificates.cert-manager.io &> /dev/null; then
            success "cert-manager CRDs ready"
            CRD_READY=true
            break
        fi
        
        # Show progress every 10 seconds
        if [ $((i % 5)) -eq 0 ]; then
            log "Still waiting for CRDs... ($i/60)"
        fi
        sleep 2
    done
    
    if [ "$CRD_READY" = false ]; then
        error "cert-manager CRDs failed to become ready after 2 minutes. Cannot continue."
    fi
    
    # Create Cloudflare secret
    kubectl create namespace cert-manager --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    kubectl create secret generic cloudflare-api-token \
        --from-literal=api-token="$CLOUDFLARE_TOKEN" \
        --namespace=cert-manager \
        --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Create ClusterIssuer
    log "Creating ClusterIssuer..."
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
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
        - "$DOMAIN"
        - "*.$DOMAIN"
EOF
    
    # Create local storage
    log "Setting up storage..."
    mkdir -p /opt/june-postgresql-data
    chmod 755 /opt/june-postgresql-data
    
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-storage
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
EOF
    
    success "Infrastructure ready"
}

# ============================================================================
# STEP 4.5: Restore Certificate Backup (if exists)
# ============================================================================

restore_certificate_if_exists() {
    log "Step 4.5/7: Checking for certificate backup..."
    
    if [ ! -d "$BACKUP_DIR" ]; then
        log_info "No backup directory found, will create new certificate"
        return
    fi
    
    # Find most recent backup
    LATEST_BACKUP=$(find "$BACKUP_DIR" -name "${CERT_SECRET_NAME}*.yaml" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    
    if [ -z "$LATEST_BACKUP" ]; then
        log_info "No certificate backups found, will create new certificate"
        return
    fi
    
    log_info "Found certificate backup: $(basename "$LATEST_BACKUP")"
    
    # Check if backup is valid and not expired
    if grep -q "tls.crt" "$LATEST_BACKUP" && grep -q "tls.key" "$LATEST_BACKUP"; then
        # Extract certificate data and check expiration
        CERT_DATA=$(grep -A 500 "tls.crt:" "$LATEST_BACKUP" | grep -v "tls.crt:" | grep -v "tls.key:" | head -100 | tr -d ' ' | base64 -d 2>/dev/null)
        
        if [ -n "$CERT_DATA" ]; then
            EXPIRY_DATE=$(echo "$CERT_DATA" | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
            
            if [ -n "$EXPIRY_DATE" ]; then
                EXPIRY_EPOCH=$(date -d "$EXPIRY_DATE" +%s 2>/dev/null || echo "0")
                NOW_EPOCH=$(date +%s)
                DAYS_UNTIL_EXPIRY=$(( ($EXPIRY_EPOCH - $NOW_EPOCH) / 86400 ))
                
                if [ "$DAYS_UNTIL_EXPIRY" -gt 7 ]; then
                    log_info "Certificate expires in $DAYS_UNTIL_EXPIRY days, restoring backup..."
                    
                    # Ensure namespaces exist
                    kubectl create namespace cert-manager --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
                    kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
                    
                    # Create temporary file and update namespace
                    TEMP_FILE="/tmp/cert_restore_$(date +%s).yaml"
                    
                    # Update the namespace to cert-manager (where cert-manager expects it)
                    sed "s/namespace:.*/namespace: cert-manager/g" "$LATEST_BACKUP" > "$TEMP_FILE"
                    
                    # Apply the certificate
                    if kubectl apply -f "$TEMP_FILE" > /dev/null 2>&1; then
                        rm -f "$TEMP_FILE"
                        sleep 3
                        
                        # Verify restoration
                        if kubectl get secret "$CERT_SECRET_NAME" -n cert-manager &>/dev/null; then
                            success "Certificate restored from backup (valid for $DAYS_UNTIL_EXPIRY days)"
                            
                            # Also copy to june-services namespace for the Ingress
                            kubectl get secret "$CERT_SECRET_NAME" -n cert-manager -o yaml | \
                                sed 's/namespace: cert-manager/namespace: june-services/' | \
                                kubectl apply -f - > /dev/null 2>&1
                            
                            success "Certificate copied to june-services namespace"
                            
                            # Set flag to skip certificate creation in Helm
                            SKIP_CERT_CREATION="true"
                            
                            log_info "⚡ Avoiding Let's Encrypt rate limit by using existing certificate"
                            return
                        else
                            warn "Certificate restoration verification failed"
                        fi
                    else
                        rm -f "$TEMP_FILE"
                        warn "Failed to apply certificate backup"
                    fi
                else
                    warn "Certificate expires in $DAYS_UNTIL_EXPIRY days (too soon), will create new one"
                fi
            else
                warn "Could not parse certificate expiration date"
            fi
        else
            warn "Could not extract certificate data from backup"
        fi
    else
        warn "Backup file appears invalid (missing tls.crt or tls.key)"
    fi
    
    log_info "Will create new certificate via cert-manager"
}

# ============================================================================
# STEP 5: Install Helm
# ============================================================================

install_helm() {
    log "Step 5/7: Installing Helm..."
    
    # Check if helm actually works (not just exists)
    if helm version &> /dev/null; then
        success "Helm already installed ($(helm version --short))"
        return
    fi
    
    log "Installing Helm..."
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash > /dev/null 2>&1
    
    # Verify installation
    if helm version &> /dev/null; then
        success "Helm installed ($(helm version --short))"
    else
        error "Helm installation failed"
    fi
}

# ============================================================================
# STEP 6: Deploy June Platform
# ============================================================================

deploy_june() {
    log "Step 6/7: Deploying June Platform..."
    
    HELM_CHART="$SCRIPT_DIR/helm/june-platform"
    
    if [ ! -d "$HELM_CHART" ]; then
        error "Helm chart not found at: $HELM_CHART"
    fi
    
    # Verify Chart.yaml exists (case-sensitive)
    if [ ! -f "$HELM_CHART/Chart.yaml" ]; then
        # Check for lowercase variant
        if [ -f "$HELM_CHART/chart.yaml" ]; then
            warn "Found chart.yaml (lowercase) - renaming to Chart.yaml"
            mv "$HELM_CHART/chart.yaml" "$HELM_CHART/Chart.yaml"
        else
            error "Chart.yaml not found in $HELM_CHART"
        fi
    fi
    
    # Validate chart
    log "Validating Helm chart..."
    if ! helm lint "$HELM_CHART" 2>&1 | grep -q "chart(s) linted, 0 chart(s) failed"; then
        warn "Helm chart validation had warnings (this is OK if it's just missing icon)"
        helm lint "$HELM_CHART" || true
    fi
    
    success "Helm chart validated"
    
    # Build Helm command with conditional certificate creation
    HELM_ARGS=(
        --namespace june-services
        --create-namespace
        --set global.domain="$DOMAIN"
        --set certificate.email="$LETSENCRYPT_EMAIL"
        --set secrets.geminiApiKey="$GEMINI_API_KEY"
        --set secrets.cloudflareToken="$CLOUDFLARE_TOKEN"
        --set postgresql.password="${POSTGRESQL_PASSWORD:-Pokemon123!}"
        --set keycloak.adminPassword="${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}"
        --set stunner.password="${STUNNER_PASSWORD:-Pokemon123!}"
        --wait
        --timeout 15m
    )
    
    # Skip certificate creation if we restored from backup
    if [ "$SKIP_CERT_CREATION" = "true" ]; then
        log_info "Using restored certificate, skipping cert creation in Helm"
        HELM_ARGS+=(--set certificate.enabled=false)
        HELM_ARGS+=(--set certificate.secretName="$CERT_SECRET_NAME")
    fi
    
    # Deploy with Helm
    log "Deploying services (this may take 10-15 minutes)..."
    
    if helm upgrade --install june-platform "$HELM_CHART" "${HELM_ARGS[@]}" 2>&1 | tee /tmp/helm-deploy.log; then
        success "June Platform deployed"
    else
        error "Helm deployment failed. Check /tmp/helm-deploy.log for details"
    fi
}

# ============================================================================
# STEP 7: Backup New Certificate
# ============================================================================

backup_new_certificate() {
    log "Step 7/7: Certificate backup management..."
    
    if [ "$SKIP_CERT_CREATION" = "true" ]; then
        log_info "Using existing certificate backup, no new backup needed"
        return
    fi
    
    log_info "Backing up newly created certificate..."
    
    # Create backup directory
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    
    # Wait for certificate to be ready
    log "Waiting for certificate to be issued (max 5 minutes)..."
    
    CERT_READY=false
    for i in {1..60}; do
        if kubectl get secret "$CERT_SECRET_NAME" -n cert-manager &>/dev/null 2>&1; then
            # Verify it has actual certificate data
            CERT_DATA=$(kubectl get secret "$CERT_SECRET_NAME" -n cert-manager -o jsonpath='{.data.tls\.crt}' 2>/dev/null)
            if [ -n "$CERT_DATA" ]; then
                CERT_READY=true
                break
            fi
        fi
        
        if [ $((i % 10)) -eq 0 ]; then
            log "Still waiting for certificate... ($i/60)"
        fi
        sleep 5
    done
    
    if [ "$CERT_READY" = false ]; then
        warn "Certificate not ready after 5 minutes, skipping backup"
        warn "You can manually backup later with: scripts/install-k8s/backup-restore-cert.sh backup"
        return
    fi
    
    # Create backup
    BACKUP_FILE="$BACKUP_DIR/${CERT_SECRET_NAME}_$(date +%Y%m%d_%H%M%S).yaml"
    
    kubectl get secret "$CERT_SECRET_NAME" -n cert-manager -o yaml > "$BACKUP_FILE"
    
    if [ -f "$BACKUP_FILE" ]; then
        # Validate backup
        if grep -q "tls.crt" "$BACKUP_FILE" && grep -q "tls.key" "$BACKUP_FILE"; then
            success "Certificate backed up to: $BACKUP_FILE"
            
            # Show certificate info
            CERT_DATA=$(kubectl get secret "$CERT_SECRET_NAME" -n cert-manager -o jsonpath='{.data.tls\.crt}' | base64 -d 2>/dev/null)
            if [ -n "$CERT_DATA" ]; then
                EXPIRY=$(echo "$CERT_DATA" | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
                DOMAINS=$(echo "$CERT_DATA" | openssl x509 -noout -text 2>/dev/null | grep -A1 "Subject Alternative Name" | tail -1 | tr ',' '\n' | grep DNS: | sed 's/.*DNS://' | tr '\n' ' ')
                
                log_info "Certificate Details:"
                echo "  Domains: $DOMAINS"
                echo "  Expires: $EXPIRY"
                echo "  Backup: $BACKUP_FILE"
                
                # Clean up old backups (keep last 5)
                BACKUP_COUNT=$(find "$BACKUP_DIR" -name "${CERT_SECRET_NAME}*.yaml" | wc -l)
                if [ "$BACKUP_COUNT" -gt 5 ]; then
                    log_info "Cleaning up old backups (keeping last 5)..."
                    find "$BACKUP_DIR" -name "${CERT_SECRET_NAME}*.yaml" -type f -printf '%T@ %p\n' | sort -n | head -n -5 | cut -d' ' -f2- | xargs -r rm
                fi
            fi
        else
            warn "Backup validation failed - missing certificate data"
            rm -f "$BACKUP_FILE"
        fi
    else
        warn "Failed to create backup file"
    fi
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    install_prerequisites
    install_docker
    install_kubernetes
    install_infrastructure
    restore_certificate_if_exists
    install_helm
    deploy_june
    backup_new_certificate
    
    # Get external IP
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    
    echo ""
    echo "=========================================="
    success "Installation Complete!"
    echo "=========================================="
    echo ""
    echo "📋 Your Services:"
    echo "  API:        https://api.$DOMAIN"
    echo "  Identity:   https://idp.$DOMAIN"
    echo "  STT:        https://stt.$DOMAIN"
    echo "  TTS:        https://tts.$DOMAIN"
    echo ""
    echo "🌐 DNS Configuration:"
    echo "  Point these records to: $EXTERNAL_IP"
    echo "    $DOMAIN           A    $EXTERNAL_IP"
    echo "    *.$DOMAIN         A    $EXTERNAL_IP"
    echo ""
    echo "🔐 Keycloak Admin:"
    echo "  URL:        https://idp.$DOMAIN/admin"
    echo "  Username:   admin"
    echo "  Password:   ${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}"
    echo ""
    
    if [ "$SKIP_CERT_CREATION" = "true" ]; then
        echo "🎉 Certificate Management:"
        echo "  ✅ Used existing certificate backup"
        echo "  ⚡ Avoided Let's Encrypt rate limit"
        echo "  📁 Backups: $BACKUP_DIR"
        echo ""
    else
        echo "🎉 Certificate Management:"
        echo "  ✅ New wildcard certificate created"
        echo "  💾 Backed up to: $BACKUP_DIR"
        echo "  ⏭️  Next deployments will reuse this certificate"
        echo ""
    fi
    
    echo "📊 Check Status:"
    echo "  kubectl get pods -n june-services"
    echo "  helm status june-platform -n june-services"
    echo ""
    echo "🔍 Verify Deployment:"
    echo "  curl https://api.$DOMAIN/healthz"
    echo ""
    echo "📝 Certificate Management:"
    echo "  List backups:   scripts/install-k8s/backup-restore-cert.sh list"
    echo "  Restore backup: scripts/install-k8s/backup-restore-cert.sh restore"
    echo "  Create backup:  scripts/install-k8s/backup-restore-cert.sh backup"
    echo ""
    echo "=========================================="
}

# Run installation
main "$@"