#!/bin/bash
# Backup Wildcard Certificate Script
# Run this ONCE after your certificate is successfully issued
# This saves you from Let's Encrypt rate limits on rebuilds

set -e

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }

echo "🔒 Wildcard Certificate Backup Tool"
echo "===================================="
echo ""

# Configuration
NAMESPACE="june-services"
SECRET_NAME="allsafe-wildcard-tls"
BACKUP_DIR="$HOME/.june-certs"
BACKUP_FILE="$BACKUP_DIR/wildcard-cert-backup.yaml"

# Create backup directory
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Check if secret exists
log_info "Checking for certificate secret..."

if ! kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" &>/dev/null; then
    log_error "Certificate secret '$SECRET_NAME' not found in namespace '$NAMESPACE'"
    echo ""
    echo "The certificate might not be issued yet. Check status:"
    echo "  kubectl get certificate -n $NAMESPACE"
    echo "  kubectl describe certificate -n $NAMESPACE"
    echo ""
    echo "Wait for cert-manager to issue the certificate, then run this script again."
    exit 1
fi

log_success "Found certificate secret"

# Check certificate status
log_info "Checking certificate status..."

CERT_READY=$(kubectl get certificate -n "$NAMESPACE" -o json 2>/dev/null | \
    jq -r '.items[] | select(.spec.secretName=="'$SECRET_NAME'") | .status.conditions[] | select(.type=="Ready") | .status' 2>/dev/null || echo "Unknown")

if [ "$CERT_READY" = "True" ]; then
    log_success "Certificate is ready and valid"
elif [ "$CERT_READY" = "False" ]; then
    log_warning "Certificate exists but is not ready yet"
    echo ""
    kubectl describe certificate -n "$NAMESPACE"
    echo ""
    read -p "Continue with backup anyway? (y/n): " CONTINUE
    [[ $CONTINUE != [yY] ]] && { echo "Cancelled."; exit 0; }
else
    log_warning "Certificate status unknown (this is normal for manual secrets)"
fi

# Backup the secret
log_info "Backing up certificate to: $BACKUP_FILE"

kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o yaml > "$BACKUP_FILE"

# Verify backup
if [ -f "$BACKUP_FILE" ] && [ -s "$BACKUP_FILE" ]; then
    log_success "Certificate backed up successfully!"
    
    # Show certificate details
    echo ""
    echo "📋 Certificate Details:"
    
    # Extract and decode certificate
    CERT_DATA=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.tls\.crt}' | base64 -d)
    
    # Show expiration
    EXPIRY=$(echo "$CERT_DATA" | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    SUBJECT=$(echo "$CERT_DATA" | openssl x509 -noout -subject 2>/dev/null | sed 's/subject=//')
    ISSUER=$(echo "$CERT_DATA" | openssl x509 -noout -issuer 2>/dev/null | sed 's/issuer=//')
    
    echo "  Subject: $SUBJECT"
    echo "  Issuer: $ISSUER"
    echo "  Expires: $EXPIRY"
    
    # Calculate days until expiry
    EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s 2>/dev/null || date -j -f "%b %d %T %Y %Z" "$EXPIRY" +%s 2>/dev/null)
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( ($EXPIRY_EPOCH - $NOW_EPOCH) / 86400 ))
    
    echo "  Days remaining: $DAYS_LEFT"
    
    if [ $DAYS_LEFT -lt 30 ]; then
        log_warning "Certificate expires in less than 30 days!"
    fi
    
else
    log_error "Backup failed!"
    exit 1
fi

# Secure the backup
chmod 600 "$BACKUP_FILE"
log_success "Backup file secured (600 permissions)"

# Create a metadata file
METADATA_FILE="$BACKUP_DIR/backup-metadata.txt"
cat > "$METADATA_FILE" << EOF
Backup Created: $(date)
Namespace: $NAMESPACE
Secret Name: $SECRET_NAME
Certificate Expiry: $EXPIRY
Days Remaining: $DAYS_LEFT
Backup File: $BACKUP_FILE
EOF

log_success "Metadata saved to: $METADATA_FILE"

echo ""
echo "======================================================"
log_success "Certificate Backup Complete!"
echo "======================================================"
echo ""
echo "📁 Backup Location:"
echo "   $BACKUP_FILE"
echo ""
echo "🔐 Security:"
echo "   • File permissions: 600 (owner read/write only)"
echo "   • Directory: $BACKUP_DIR"
echo "   • Contains private key - keep secure!"
echo ""
echo "📋 Next Steps:"
echo "   1. Keep this backup safe"
echo "   2. When you rebuild, stage2 will automatically restore it"
echo "   3. No more Let's Encrypt rate limit issues!"
echo ""
echo "🔄 To manually restore (if needed):"
echo "   kubectl apply -f $BACKUP_FILE"
echo ""
echo "⏰ Certificate Renewal:"
echo "   • Expires: $EXPIRY ($DAYS_LEFT days)"
echo "   • cert-manager will auto-renew ~30 days before expiry"
echo "   • Run this backup script again after renewal"
echo ""
echo "======================================================"