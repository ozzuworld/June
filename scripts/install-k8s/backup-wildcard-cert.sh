#!/bin/bash
# Backup Wildcard Certificate Script
# Creates a backup of the current wildcard certificate for disaster recovery
# Usage: ./backup-wildcard-cert.sh [certificate-secret-name]

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
echo "💾  Certificate Backup Utility"
echo "======================================================"
echo ""

# Configuration
CONFIG_DIR="/root/.june-config"
CERT_BACKUP_DIR="/root/.june-certs"
NAMESPACE="june-services"

# Create backup directory
mkdir -p "$CERT_BACKUP_DIR"
chmod 700 "$CERT_BACKUP_DIR"

# Load domain configuration if available
if [ -f "$CONFIG_DIR/domain-config.env" ]; then
    log_info "Loading domain configuration..."
    source "$CONFIG_DIR/domain-config.env"
fi

# Determine certificate secret name
if [ -n "$1" ]; then
    CERT_SECRET_NAME="$1"
    log_info "Using provided certificate name: $CERT_SECRET_NAME"
elif [ -n "$CERT_SECRET_NAME" ]; then
    log_info "Using certificate name from config: $CERT_SECRET_NAME"
else
    log_info "Auto-detecting certificate secrets..."
    
    # Look for wildcard certificate secrets
    WILDCARD_SECRETS=$(kubectl get secrets -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' | grep -E '(wildcard|tls)' | head -5)
    
    if [ -z "$WILDCARD_SECRETS" ]; then
        log_error "No wildcard certificate secrets found in namespace $NAMESPACE"
        log_info "Available secrets:"
        kubectl get secrets -n "$NAMESPACE" | grep -v "Opaque\|kubernetes.io" || echo "  No TLS secrets found"
        exit 1
    fi
    
    echo "Found potential certificate secrets:"
    echo "$WILDCARD_SECRETS" | nl
    echo ""
    
    if [ $(echo "$WILDCARD_SECRETS" | wc -l) -eq 1 ]; then
        CERT_SECRET_NAME="$WILDCARD_SECRETS"
        log_info "Auto-selected: $CERT_SECRET_NAME"
    else
        echo "Multiple certificate secrets found. Please specify one:"
        echo "$WILDCARD_SECRETS" | nl
        echo ""
        read -p "Enter the number or full name of the certificate to backup: " SELECTION
        
        if [[ "$SELECTION" =~ ^[0-9]+$ ]]; then
            CERT_SECRET_NAME=$(echo "$WILDCARD_SECRETS" | sed -n "${SELECTION}p")
        else
            CERT_SECRET_NAME="$SELECTION"
        fi
        
        if [ -z "$CERT_SECRET_NAME" ]; then
            log_error "Invalid selection"
            exit 1
        fi
    fi
fi

log_info "Selected certificate secret: $CERT_SECRET_NAME"

# Verify the secret exists and is a TLS secret
log_info "Validating certificate secret..."

if ! kubectl get secret "$CERT_SECRET_NAME" -n "$NAMESPACE" &>/dev/null; then
    log_error "Certificate secret '$CERT_SECRET_NAME' not found in namespace '$NAMESPACE'"
    log_info "Available secrets:"
    kubectl get secrets -n "$NAMESPACE"
    exit 1
fi

# Check if it's a TLS secret
SECRET_TYPE=$(kubectl get secret "$CERT_SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.type}')
if [ "$SECRET_TYPE" != "kubernetes.io/tls" ]; then
    log_error "Secret '$CERT_SECRET_NAME' is not a TLS secret (type: $SECRET_TYPE)"
    exit 1
fi

# Verify it has the required TLS fields
TLS_CRT=$(kubectl get secret "$CERT_SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.tls\.crt}' 2>/dev/null)
TLS_KEY=$(kubectl get secret "$CERT_SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.tls\.key}' 2>/dev/null)

if [ -z "$TLS_CRT" ] || [ -z "$TLS_KEY" ]; then
    log_error "Certificate secret is missing tls.crt or tls.key data"
    exit 1
fi

log_success "Certificate secret validation passed"

# Extract certificate information for validation
log_info "Analyzing certificate..."

# Decode certificate and extract information
echo "$TLS_CRT" | base64 -d > /tmp/cert_analysis.crt 2>/dev/null || {
    log_error "Failed to decode certificate data"
    exit 1
}

# Get certificate details
CERT_SUBJECT=$(openssl x509 -in /tmp/cert_analysis.crt -noout -subject 2>/dev/null | sed 's/subject=//')
CERT_ISSUER=$(openssl x509 -in /tmp/cert_analysis.crt -noout -issuer 2>/dev/null | sed 's/issuer=//')
CERT_EXPIRY=$(openssl x509 -in /tmp/cert_analysis.crt -noout -enddate 2>/dev/null | cut -d= -f2)
CERT_DOMAINS=$(openssl x509 -in /tmp/cert_analysis.crt -noout -text 2>/dev/null | grep -A1 "Subject Alternative Name" | tail -1 | tr ',' '\n' | grep DNS: | sed 's/.*DNS://' | tr '\n' ' ' | sed 's/ $//')

# Calculate days until expiry
if [ -n "$CERT_EXPIRY" ]; then
    EXPIRY_EPOCH=$(date -d "$CERT_EXPIRY" +%s 2>/dev/null)
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
else
    DAYS_LEFT="unknown"
fi

echo ""
log_info "📋 Certificate Information:"
echo "  Subject: $CERT_SUBJECT"
echo "  Issuer: $CERT_ISSUER"
echo "  Expires: $CERT_EXPIRY"
if [ "$DAYS_LEFT" != "unknown" ]; then
    if [ $DAYS_LEFT -lt 0 ]; then
        echo "  Status: ❌ EXPIRED ($((0-DAYS_LEFT)) days ago)"
    elif [ $DAYS_LEFT -lt 30 ]; then
        echo "  Status: ⚠️  Expires soon ($DAYS_LEFT days)"
    else
        echo "  Status: ✅ Valid ($DAYS_LEFT days remaining)"
    fi
else
    echo "  Status: ❓ Could not determine expiry"
fi
echo "  Domains: $CERT_DOMAINS"
echo ""

# Warn about expired certificates
if [ "$DAYS_LEFT" != "unknown" ] && [ $DAYS_LEFT -lt 0 ]; then
    log_warning "This certificate has expired! Consider renewing before backup."
    read -p "Continue with backup anyway? [y/N]: " CONTINUE_EXPIRED
    if [[ ! "$CONTINUE_EXPIRED" =~ ^[Yy]$ ]]; then
        log_info "Backup cancelled"
        rm -f /tmp/cert_analysis.crt
        exit 0
    fi
fi

# Generate backup filename with timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILENAME="${CERT_SECRET_NAME}-backup-${TIMESTAMP}.yaml"
BACKUP_PATH="$CERT_BACKUP_DIR/$BACKUP_FILENAME"

log_info "Creating certificate backup..."
log_info "Backup file: $BACKUP_PATH"

# Create the backup with metadata
cat > "$BACKUP_PATH" << EOF
# Certificate Backup Created: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
# Original Secret: $CERT_SECRET_NAME
# Namespace: $NAMESPACE
# Domains: $CERT_DOMAINS
# Expires: $CERT_EXPIRY
# Backup Script Version: 1.0
#
# To restore this certificate:
#   kubectl apply -f $BACKUP_FILENAME
#
# Note: You may need to update the namespace if restoring to a different cluster

EOF

# Export the secret
kubectl get secret "$CERT_SECRET_NAME" -n "$NAMESPACE" -o yaml >> "$BACKUP_PATH" 2>/dev/null || {
    log_error "Failed to export certificate secret"
    rm -f "$BACKUP_PATH"
    rm -f /tmp/cert_analysis.crt
    exit 1
}

# Clean up temporary files
rm -f /tmp/cert_analysis.crt

# Set secure permissions on backup
chmod 600 "$BACKUP_PATH"

# Verify backup file
if [ -f "$BACKUP_PATH" ] && grep -q "tls.crt" "$BACKUP_PATH" && grep -q "tls.key" "$BACKUP_PATH"; then
    BACKUP_SIZE=$(stat -f%z "$BACKUP_PATH" 2>/dev/null || stat -c%s "$BACKUP_PATH" 2>/dev/null)
    log_success "Certificate backup created successfully!"
    log_info "Backup details:"
    echo "  File: $BACKUP_PATH"
    echo "  Size: ${BACKUP_SIZE} bytes"
    echo "  Permissions: $(ls -la \"$BACKUP_PATH\" | awk '{print $1}')"
else
    log_error "Backup verification failed"
    rm -f "$BACKUP_PATH"
    exit 1
fi

# Clean up old backups (keep last 5)
log_info "Cleaning up old backups..."
OLD_BACKUPS=$(find "$CERT_BACKUP_DIR" -name "*-backup-*.yaml" -type f | sort -r | tail -n +6)
if [ -n "$OLD_BACKUPS" ]; then
    echo "$OLD_BACKUPS" | while read -r old_backup; do
        log_info "Removing old backup: $(basename \"$old_backup\")"
        rm -f "$old_backup"
    done
else
    log_info "No old backups to clean up"
fi

# Show all current backups
log_info "Current certificate backups:"
ls -la "$CERT_BACKUP_DIR"/*.yaml 2>/dev/null | while read -r line; do
    echo "  $line"
done || echo "  No backup files found"

echo ""
echo "======================================================"
log_success "🎉 Certificate Backup Complete!"
echo "======================================================"
echo ""
echo "💾 Backup Information:"
echo "  Certificate: $CERT_SECRET_NAME"
echo "  Backup File: $BACKUP_FILENAME"
echo "  Location: $CERT_BACKUP_DIR"
echo "  Domains: $CERT_DOMAINS"
if [ "$DAYS_LEFT" != "unknown" ]; then
    echo "  Expires: in $DAYS_LEFT days"
fi
echo ""
echo "🔒 Security Notes:"
echo "  • Backup files contain private keys - keep secure!"
echo "  • Files are stored with 600 permissions (owner read/write only)"
echo "  • Consider encrypting backups for long-term storage"
echo ""
echo "🔄 Restoration:"
echo "  To restore this certificate:"
echo "    kubectl apply -f $CERT_BACKUP_DIR/$BACKUP_FILENAME"
echo ""
echo "======================================================"