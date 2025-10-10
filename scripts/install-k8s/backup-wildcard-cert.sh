#!/bin/bash
# Certificate Backup Script for June Platform
# Usage: ./backup-wildcard-cert.sh [certificate-name] [namespace]

set -euo pipefail

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

CONFIG_DIR="/root/.june-config"
BACKUP_DIR="/root/.june-certs"

# Load configuration if available
if [ -f "$CONFIG_DIR/domain-config.env" ]; then
    source "$CONFIG_DIR/domain-config.env"
fi

# Use provided arguments or try to detect from configuration
CERT_NAME="${1:-${CERT_NAME:-}}"
NAMESPACE="${2:-june-services}"

# If no certificate name provided, try to find one
if [ -z "$CERT_NAME" ]; then
    log_info "No certificate name provided, scanning for certificates..."
    
    # Try to find certificates by pattern
    FOUND_CERTS=($(kubectl get certificates -n "$NAMESPACE" -o name 2>/dev/null | grep -E "(wildcard|allsafe)" | head -5 || echo ""))
    
    if [ ${#FOUND_CERTS[@]} -gt 0 ]; then
        echo ""
        log_info "Found certificates:"
        for i in "${!FOUND_CERTS[@]}"; do
            CERT_RESOURCE="${FOUND_CERTS[$i]#certificate.cert-manager.io/}"
            echo "  $((i+1)). $CERT_RESOURCE"
        done
        echo ""
        
        if [ ${#FOUND_CERTS[@]} -eq 1 ]; then
            CERT_NAME="${FOUND_CERTS[0]#certificate.cert-manager.io/}"
            log_info "Using certificate: $CERT_NAME"
        else
            read -p "Select certificate [1-${#FOUND_CERTS[@]}]: " CERT_CHOICE
            if [[ "$CERT_CHOICE" -ge 1 && "$CERT_CHOICE" -le "${#FOUND_CERTS[@]}" ]]; then
                CERT_NAME="${FOUND_CERTS[$((CERT_CHOICE-1))]#certificate.cert-manager.io/}"
                log_info "Selected certificate: $CERT_NAME"
            else
                log_error "Invalid selection"
                exit 1
            fi
        fi
    else
        log_error "No certificates found in namespace '$NAMESPACE'"
        log_info "Available certificates:"
        kubectl get certificates -n "$NAMESPACE" 2>/dev/null || echo "None found"
        exit 1
    fi
fi

TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo "======================================================"
log_info "🔐 Certificate Backup Utility"
echo "======================================================"
echo ""

log_info "Backing up certificate: $CERT_NAME from namespace: $NAMESPACE"

# Check if certificate resource exists
if kubectl get certificate "$CERT_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
    # Get the secret name from the certificate
    SECRET_NAME=$(kubectl get certificate "$CERT_NAME" -n "$NAMESPACE" -o jsonpath='{.spec.secretName}' 2>/dev/null || echo "unknown")
    
    if [ "$SECRET_NAME" = "unknown" ]; then
        log_warning "Could not determine secret name from certificate"
        SECRET_NAME="${CERT_NAME}-tls"
        log_info "Using default secret name: $SECRET_NAME"
    fi
    
    log_info "Certificate secret name: $SECRET_NAME"
    
    # Backup certificate resource
    kubectl get certificate "$CERT_NAME" -n "$NAMESPACE" -o yaml > \
        "$BACKUP_DIR/${CERT_NAME}-resource-${TIMESTAMP}.yaml"
    log_success "Certificate resource backed up"
    
    # Backup certificate secret
    if kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
        kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o yaml > \
            "$BACKUP_DIR/${SECRET_NAME}-secret-${TIMESTAMP}.yaml"
        log_success "Certificate secret backed up"
        
        # Create a restore-friendly backup (main backup file)
        cp "$BACKUP_DIR/${SECRET_NAME}-secret-${TIMESTAMP}.yaml" \
           "$BACKUP_DIR/${SECRET_NAME}-backup-${TIMESTAMP}.yaml"
        
        # Validate certificate and show info
        CERT_DATA=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.tls\.crt}' 2>/dev/null || echo "")
        if [ -n "$CERT_DATA" ]; then
            echo "$CERT_DATA" | base64 -d > "/tmp/cert_info.crt"
            
            # Show certificate info
            log_info "Certificate Information:"
            CERT_SUBJECT=$(openssl x509 -in "/tmp/cert_info.crt" -noout -subject 2>/dev/null | cut -d= -f2- || echo "unknown")
            CERT_EXPIRY=$(openssl x509 -in "/tmp/cert_info.crt" -noout -enddate 2>/dev/null | cut -d= -f2 || echo "unknown")
            CERT_DOMAINS=$(openssl x509 -in "/tmp/cert_info.crt" -noout -text 2>/dev/null | grep -A1 "Subject Alternative Name" | tail -1 | tr ',' '\n' | grep DNS: | sed 's/.*DNS://' | tr '\n' ' ' || echo "unknown")
            
            echo "  Subject: $CERT_SUBJECT"
            echo "  Expiry: $CERT_EXPIRY"
            echo "  Domains: $CERT_DOMAINS"
            
            # Calculate days until expiry
            if [ "$CERT_EXPIRY" != "unknown" ]; then
                EXPIRY_EPOCH=$(date -d "$CERT_EXPIRY" +%s 2>/dev/null || echo "0")
                NOW_EPOCH=$(date +%s)
                DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
                
                if [ $DAYS_LEFT -lt 0 ]; then
                    log_error "Certificate has expired!"
                elif [ $DAYS_LEFT -lt 30 ]; then
                    log_warning "Certificate expires in $DAYS_LEFT days"
                else
                    log_success "Certificate is valid ($DAYS_LEFT days remaining)"
                fi
            fi
            
            rm -f "/tmp/cert_info.crt"
            
            # Also save raw certificate files
            echo "$CERT_DATA" | base64 -d > "$BACKUP_DIR/${SECRET_NAME}-${TIMESTAMP}.crt"
            kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.tls\.key}' | base64 -d > \
                "$BACKUP_DIR/${SECRET_NAME}-${TIMESTAMP}.key"
            
            log_success "Raw certificate files saved"
            
            # Create symlink to latest backup for easy access
            cd "$BACKUP_DIR"
            ln -sf "${SECRET_NAME}-backup-${TIMESTAMP}.yaml" "${SECRET_NAME}-latest-backup.yaml" 2>/dev/null || true
            
            # Cleanup old backups (keep last 10)
            ls -t ${SECRET_NAME}-backup-*.yaml 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
            
        else
            log_warning "Certificate secret exists but contains no certificate data"
        fi
    else
        log_error "Certificate secret '$SECRET_NAME' not found"
    fi
    
else
    log_error "Certificate '$CERT_NAME' not found in namespace '$NAMESPACE'"
    
    # Try to find certificates by pattern
    log_info "Searching for certificates with 'wildcard' in name..."
    FOUND_CERTS=($(kubectl get certificates -n "$NAMESPACE" -o name 2>/dev/null | grep -i wildcard | head -5 || echo ""))
    
    if [ ${#FOUND_CERTS[@]} -gt 0 ]; then
        log_info "Found certificates:"
        for cert in "${FOUND_CERTS[@]}"; do
            echo "  - ${cert#certificate.cert-manager.io/}"
        done
        echo ""
        log_info "Retry with: $0 <certificate-name> $NAMESPACE"
    else
        log_info "No wildcard certificates found in namespace $NAMESPACE"
    fi
    
    exit 1
fi

echo ""
log_success "🎉 Backup completed successfully!"
echo "Backup location: $BACKUP_DIR"
echo "Files created:"
ls -la "$BACKUP_DIR/" | grep "$TIMESTAMP" | awk '{print "  " $9 " (" $5 " bytes)"}'

echo ""
log_info "💡 Restore instructions:"
echo "  kubectl apply -f $BACKUP_DIR/${SECRET_NAME}-backup-${TIMESTAMP}.yaml"
echo ""
log_info "Latest backup symlink:"
echo "  $BACKUP_DIR/${SECRET_NAME}-latest-backup.yaml"

echo ""
echo "======================================================"
