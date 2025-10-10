#!/bin/bash
# Certificate Backup and Restore Script for June Platform
# Usage: 
#   ./backup-restore-cert.sh backup
#   ./backup-restore-cert.sh restore
#   ./backup-restore-cert.sh list

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

# Configuration
CONFIG_DIR="/root/.june-config"
BACKUP_DIR="/root/.june-certs"
NAMESPACE="june-services"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Function to backup certificate
backup_certificate() {
    log_info "Starting certificate backup..."
    
    # Load domain config
    if [ -f "$CONFIG_DIR/domain-config.env" ]; then
        source "$CONFIG_DIR/domain-config.env"
    fi
    
    # Default certificate name if not configured
    CERT_SECRET_NAME=${CERT_SECRET_NAME:-"allsafe-wildcard-tls"}
    
    # Check if certificate exists
    if ! kubectl get secret "$CERT_SECRET_NAME" -n "$NAMESPACE" &>/dev/null; then
        log_error "Certificate secret '$CERT_SECRET_NAME' not found in namespace '$NAMESPACE'"
        exit 1
    fi
    
    # Create backup filename with timestamp
    BACKUP_FILE="$BACKUP_DIR/${CERT_SECRET_NAME}_$(date +%Y%m%d_%H%M%S).yaml"
    
    # Export certificate
    kubectl get secret "$CERT_SECRET_NAME" -n "$NAMESPACE" -o yaml > "$BACKUP_FILE"
    
    if [ -f "$BACKUP_FILE" ]; then
        # Validate backup
        if grep -q "tls.crt" "$BACKUP_FILE" && grep -q "tls.key" "$BACKUP_FILE"; then
            log_success "Certificate backed up to: $BACKUP_FILE"
            
            # Show certificate info
            CERT_DATA=$(kubectl get secret "$CERT_SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.tls\.crt}' | base64 -d)
            EXPIRY=$(echo "$CERT_DATA" | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
            DOMAINS=$(echo "$CERT_DATA" | openssl x509 -noout -text 2>/dev/null | grep -A1 "Subject Alternative Name" | tail -1 | tr ',' '\n' | grep DNS: | sed 's/.*DNS://' | tr '\n' ' ')
            
            echo ""
            log_info "Certificate Details:"
            echo "  Secret Name: $CERT_SECRET_NAME"
            echo "  Domains: $DOMAINS"
            echo "  Expires: $EXPIRY"
            echo "  Backup File: $BACKUP_FILE"
        else
            log_error "Backup file validation failed - missing certificate data"
            rm -f "$BACKUP_FILE"
            exit 1
        fi
    else
        log_error "Failed to create backup file"
        exit 1
    fi
}

# Function to list available backups
list_backups() {
    log_info "Available certificate backups:"
    
    if [ ! -d "$BACKUP_DIR" ]; then
        log_warning "No backup directory found: $BACKUP_DIR"
        return
    fi
    
    BACKUPS=($(find "$BACKUP_DIR" -name "*.yaml" | sort -r))
    
    if [ ${#BACKUPS[@]} -eq 0 ]; then
        log_warning "No certificate backups found in $BACKUP_DIR"
        return
    fi
    
    echo ""
    for i in "${!BACKUPS[@]}"; do
        BACKUP_FILE="${BACKUPS[$i]}"
        BACKUP_DATE=$(stat -c %y "$BACKUP_FILE" 2>/dev/null | cut -d' ' -f1 || echo "unknown")
        BACKUP_NAME=$(basename "$BACKUP_FILE" .yaml)
        SECRET_NAME="unknown"
        
        # Try to extract secret name from backup
        if grep -q "name:" "$BACKUP_FILE"; then
            SECRET_NAME=$(grep "name:" "$BACKUP_FILE" | grep -v "namespace" | head -1 | awk '{print $2}' | tr -d '"')
        fi
        
        echo "  $((i+1)). $BACKUP_NAME"
        echo "     Secret: $SECRET_NAME"
        echo "     Date: $BACKUP_DATE"
        echo "     File: $BACKUP_FILE"
        echo ""
    done
}

# Function to restore certificate
restore_certificate() {
    log_info "Starting certificate restore..."
    
    # List available backups
    list_backups
    
    BACKUPS=($(find "$BACKUP_DIR" -name "*.yaml" | sort -r))
    
    if [ ${#BACKUPS[@]} -eq 0 ]; then
        log_error "No backups available for restore"
        exit 1
    fi
    
    echo "Select backup to restore:"
    read -p "Enter number [1-${#BACKUPS[@]}]: " CHOICE
    
    if [[ "$CHOICE" -ge 1 && "$CHOICE" -le "${#BACKUPS[@]}" ]]; then
        SELECTED_BACKUP="${BACKUPS[$((CHOICE-1))]}"
        log_info "Selected: $(basename "$SELECTED_BACKUP")"
    else
        log_error "Invalid selection"
        exit 1
    fi
    
    # Validate backup file
    if [ ! -f "$SELECTED_BACKUP" ]; then
        log_error "Backup file not found: $SELECTED_BACKUP"
        exit 1
    fi
    
    if ! grep -q "kind: Secret" "$SELECTED_BACKUP" || ! grep -q "tls.crt" "$SELECTED_BACKUP"; then
        log_error "Invalid backup file structure"
        exit 1
    fi
    
    # Extract secret name from backup
    SECRET_NAME=$(grep "name:" "$SELECTED_BACKUP" | grep -v "namespace" | head -1 | awk '{print $2}' | tr -d '"')
    
    if [ -z "$SECRET_NAME" ]; then
        log_error "Could not extract secret name from backup"
        exit 1
    fi
    
    log_info "Restoring certificate secret: $SECRET_NAME"
    
    # Ensure namespace exists
    kubectl create namespace "$NAMESPACE" || true
    
    # Create temporary file with correct namespace
    TEMP_FILE="/tmp/cert_restore_$(date +%s).yaml"
    sed "s/namespace:.*/namespace: $NAMESPACE/g" "$SELECTED_BACKUP" > "$TEMP_FILE"
    
    # Apply the certificate
    if kubectl apply -f "$TEMP_FILE"; then
        rm -f "$TEMP_FILE"
        
        # Wait a moment for the secret to be available
        sleep 2
        
        # Verify restoration
        if kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" &>/dev/null; then
            log_success "Certificate restored successfully: $SECRET_NAME"
            
            # Show certificate info
            CERT_DATA=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.tls\.crt}' | base64 -d 2>/dev/null || echo "")
            if [ -n "$CERT_DATA" ]; then
                EXPIRY=$(echo "$CERT_DATA" | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || echo "unknown")
                DOMAINS=$(echo "$CERT_DATA" | openssl x509 -noout -text 2>/dev/null | grep -A1 "Subject Alternative Name" | tail -1 | tr ',' '\n' | grep DNS: | sed 's/.*DNS://' | tr '\n' ' ' || echo "unknown")
                
                echo ""
                log_info "Restored Certificate Details:"
                echo "  Secret Name: $SECRET_NAME"
                echo "  Namespace: $NAMESPACE"
                echo "  Domains: $DOMAINS"
                echo "  Expires: $EXPIRY"
                
                # Update domain config if it exists
                if [ -f "$CONFIG_DIR/domain-config.env" ]; then
                    if ! grep -q "CERT_SECRET_NAME=" "$CONFIG_DIR/domain-config.env"; then
                        echo "CERT_SECRET_NAME=$SECRET_NAME" >> "$CONFIG_DIR/domain-config.env"
                    else
                        sed -i "s/^CERT_SECRET_NAME=.*/CERT_SECRET_NAME=$SECRET_NAME/" "$CONFIG_DIR/domain-config.env"
                    fi
                    log_info "Updated domain config with restored certificate name"
                fi
            else
                log_warning "Could not read certificate data for validation"
            fi
        else
            log_error "Certificate restoration failed - secret not found after restore"
            exit 1
        fi
    else
        rm -f "$TEMP_FILE"
        log_error "Failed to apply certificate from backup"
        exit 1
    fi
}

# Main script logic
case "${1:-}" in
    "backup")
        backup_certificate
        ;;
    "restore")
        restore_certificate
        ;;
    "list")
        list_backups
        ;;
    *)
        echo "Usage: $0 {backup|restore|list}"
        echo ""
        echo "Commands:"
        echo "  backup   - Backup current certificate to $BACKUP_DIR"
        echo "  restore  - Restore certificate from backup"
        echo "  list     - List available certificate backups"
        echo ""
        echo "Examples:"
        echo "  $0 backup"
        echo "  $0 list"
        echo "  $0 restore"
        exit 1
        ;;
esac