#!/bin/bash
# June Platform - Phase 6: Certificate Management
# Handles wildcard certificate restoration and creation

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

# Source configuration from environment or config file
if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

# Certificate backup directory
CERT_BACKUP_DIR="/root/.june-certs"

# Function to convert domain to backup filename format
domain_to_filename() {
    local domain="$1"
    # Convert dots to dashes for filename
    echo "${domain//\./-}"
}

# Function to check if certificate backup exists
check_certificate_backup() {
    local domain="$1"
    local domain_filename=$(domain_to_filename "$domain")
    local backup_file="${CERT_BACKUP_DIR}/${domain_filename}-wildcard-tls-backup.yaml"
    
    if [ -f "$backup_file" ]; then
        log "Found certificate backup: $backup_file"
        return 0
    else
        log "No certificate backup found: $backup_file"
        return 1
    fi
}

# Function to restore certificate from backup
restore_certificate_backup() {
    local domain="$1"
    local domain_filename=$(domain_to_filename "$domain")
    local backup_file="${CERT_BACKUP_DIR}/${domain_filename}-wildcard-tls-backup.yaml"
    
    log "Restoring wildcard certificate from backup for domain: $domain"
    
    # Validate backup file exists and is readable
    if [ ! -f "$backup_file" ]; then
        error "Certificate backup file not found: $backup_file"
    fi
    
    if [ ! -r "$backup_file" ]; then
        error "Certificate backup file is not readable: $backup_file"
    fi
    
    # Validate backup file contains certificate data
    if ! grep -q "apiVersion: v1" "$backup_file" || ! grep -q "kind: Secret" "$backup_file"; then
        error "Invalid certificate backup file format: $backup_file"
    fi
    
    # Apply the certificate backup
    log "Applying certificate backup..."
    if kubectl apply -f "$backup_file" > /dev/null 2>&1; then
        success "Certificate backup restored successfully"
        
        # Wait for certificate to be ready
        local cert_name="${domain_filename}-wildcard-tls"
        log "Waiting for certificate to be ready: $cert_name"
        
        # Check if certificate secret exists
        local timeout=60
        local counter=0
        while [ $counter -lt $timeout ]; do
            if kubectl get secret "$cert_name" -n june-services &> /dev/null; then
                success "Certificate secret is available: $cert_name"
                return 0
            fi
            sleep 2
            counter=$((counter + 2))
        done
        
        warn "Certificate secret not found after restoration, but backup was applied"
    else
        error "Failed to apply certificate backup: $backup_file"
    fi
}

# Function to create new wildcard certificate using Cloudflare DNS01
create_new_certificate() {
    local domain="$1"
    local domain_filename=$(domain_to_filename "$domain")
    
    log "Creating new wildcard certificate for domain: $domain using Cloudflare DNS01"
    
    # Validate required variables
    if [ -z "$CLOUDFLARE_TOKEN" ]; then
        error "CLOUDFLARE_TOKEN environment variable is required for DNS01 challenge"
    fi
    
    if [ -z "$LETSENCRYPT_EMAIL" ]; then
        error "LETSENCRYPT_EMAIL environment variable is required"
    fi
    
    # Ensure cert-manager is ready
    if ! kubectl get clusterissuer letsencrypt-prod &> /dev/null; then
        error "ClusterIssuer 'letsencrypt-prod' not found. Run infrastructure setup first."
    fi
    
    # Create certificate resource
    local cert_name="${domain_filename}-wildcard-tls"
    
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: $cert_name
  namespace: june-services
spec:
  secretName: $cert_name
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: "*.$domain"
  dnsNames:
  - "$domain"
  - "*.$domain"
EOF
    
    success "Certificate resource created: $cert_name"
    
    # Wait for certificate to be issued
    log "Waiting for certificate to be issued (this may take several minutes)..."
    local timeout=600  # 10 minutes
    local counter=0
    
    while [ $counter -lt $timeout ]; do
        # Check certificate status
        local cert_status=$(kubectl get certificate "$cert_name" -n june-services -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
        
        if [ "$cert_status" = "True" ]; then
            success "Wildcard certificate issued successfully for: $domain"
            
            # Create backup of the new certificate
            create_certificate_backup "$domain"
            return 0
        elif [ "$cert_status" = "False" ]; then
            # Get failure reason
            local cert_message=$(kubectl get certificate "$cert_name" -n june-services -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}' 2>/dev/null || echo "Unknown error")
            warn "Certificate issuance failed: $cert_message"
            
            # Check certificate request for more details
            local cert_request=$(kubectl get certificaterequest -n june-services -l "cert-manager.io/certificate-name=$cert_name" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
            if [ -n "$cert_request" ]; then
                log "Certificate request details:"
                kubectl describe certificaterequest "$cert_request" -n june-services || true
            fi
            
            error "Failed to issue certificate for domain: $domain"
        fi
        
        # Show progress every 30 seconds
        if [ $((counter % 30)) -eq 0 ]; then
            log "Still waiting for certificate... ($counter/${timeout}s) Status: $cert_status"
            
            # Show certificate events for debugging
            kubectl describe certificate "$cert_name" -n june-services | tail -10 || true
        fi
        
        sleep 5
        counter=$((counter + 5))
    done
    
    error "Certificate issuance timed out after ${timeout} seconds"
}

# Function to create certificate backup
create_certificate_backup() {
    local domain="$1"
    local domain_filename=$(domain_to_filename "$domain")
    local cert_name="${domain_filename}-wildcard-tls"
    local backup_file="${CERT_BACKUP_DIR}/${domain_filename}-wildcard-tls-backup.yaml"
    
    log "Creating certificate backup for domain: $domain"
    
    # Create backup directory if it doesn't exist
    mkdir -p "$CERT_BACKUP_DIR"
    
    # Export certificate secret
    if kubectl get secret "$cert_name" -n june-services -o yaml > "$backup_file" 2>/dev/null; then
        # Clean up the exported YAML (remove runtime fields)
        sed -i '/^  resourceVersion:/d; /^  uid:/d; /^  creationTimestamp:/d; /^  managedFields:/,$d' "$backup_file"
        
        success "Certificate backup created: $backup_file"
        
        # Set proper permissions
        chmod 600 "$backup_file"
        
        log "Certificate backup location: $backup_file"
    else
        error "Failed to create certificate backup for: $cert_name"
    fi
}

# Function to verify certificate is working
verify_certificate() {
    local domain="$1"
    local domain_filename=$(domain_to_filename "$domain")
    local cert_name="${domain_filename}-wildcard-tls"
    
    log "Verifying certificate: $cert_name"
    
    # Check if secret exists and has required fields
    if kubectl get secret "$cert_name" -n june-services &> /dev/null; then
        # Check if secret has tls.crt and tls.key
        local has_crt=$(kubectl get secret "$cert_name" -n june-services -o jsonpath='{.data.tls\.crt}' 2>/dev/null)
        local has_key=$(kubectl get secret "$cert_name" -n june-services -o jsonpath='{.data.tls\.key}' 2>/dev/null)
        
        if [ -n "$has_crt" ] && [ -n "$has_key" ]; then
            success "Certificate verification passed: $cert_name"
            
            # Show certificate details
            log "Certificate details:"
            kubectl get secret "$cert_name" -n june-services -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -subject -dates 2>/dev/null || true
            
            return 0
        else
            warn "Certificate secret exists but missing tls.crt or tls.key"
        fi
    else
        warn "Certificate secret not found: $cert_name"
    fi
    
    return 1
}

# Function to list available certificate backups
list_certificate_backups() {
    log "Available certificate backups in $CERT_BACKUP_DIR:"
    
    if [ -d "$CERT_BACKUP_DIR" ]; then
        local backups=($(find "$CERT_BACKUP_DIR" -name "*-wildcard-tls-backup.yaml" -type f 2>/dev/null))
        
        if [ ${#backups[@]} -gt 0 ]; then
            for backup in "${backups[@]}"; do
                local basename=$(basename "$backup")
                local domain=$(echo "$basename" | sed 's/-wildcard-tls-backup\.yaml$//' | sed 's/-/\./g')
                local filesize=$(du -h "$backup" | cut -f1)
                local modified=$(date -r "$backup" "+%Y-%m-%d %H:%M:%S")
                log "  - $domain: $backup ($filesize, modified: $modified)"
            done
        else
            log "  No certificate backups found"
        fi
    else
        log "  Certificate backup directory does not exist: $CERT_BACKUP_DIR"
    fi
}

# Function to handle certificate management workflow
manage_certificates() {
    local domain="$1"
    
    log "Managing certificates for domain: $domain"
    
    # Create june-services namespace if it doesn't exist
    kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    
    # Check if certificate already exists and is valid
    if verify_certificate "$domain"; then
        success "Valid certificate already exists for domain: $domain"
        return 0
    fi
    
    # Try to restore from backup first
    if check_certificate_backup "$domain"; then
        log "Attempting to restore certificate from backup..."
        if restore_certificate_backup "$domain"; then
            if verify_certificate "$domain"; then
                success "Certificate successfully restored from backup"
                return 0
            else
                warn "Certificate restored from backup but verification failed"
            fi
        else
            warn "Failed to restore certificate from backup"
        fi
    fi
    
    # Create new certificate using Cloudflare DNS01 challenge
    log "No valid backup found or restoration failed, creating new certificate..."
    create_new_certificate "$domain"
    
    # Verify the new certificate
    if verify_certificate "$domain"; then
        success "New certificate created and verified successfully"
    else
        error "New certificate creation failed verification"
    fi
}

# Function to show certificate management help
show_certificate_help() {
    echo "Certificate Management Commands:"
    echo "  Normal operation: Automatically manages certificates for configured domain"
    echo "  Manual commands:"
    echo "    kubectl get certificates -n june-services"
    echo "    kubectl describe certificate <cert-name> -n june-services"
    echo "    kubectl get secrets -n june-services | grep tls"
    echo ""
    echo "Backup locations:"
    echo "  Directory: $CERT_BACKUP_DIR"
    echo "  Format: {domain-with-dashes}-wildcard-tls-backup.yaml"
    echo ""
}

# Main execution
main() {
    log "Starting certificate management phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    # Verify required tools
    verify_command "kubectl" "kubectl must be available"
    verify_command "openssl" "openssl must be available"
    
    # Verify Kubernetes is running
    if ! kubectl cluster-info &> /dev/null; then
        error "Kubernetes cluster must be running"
    fi
    
    # Verify cert-manager is installed
    if ! kubectl get namespace cert-manager &> /dev/null; then
        error "cert-manager must be installed first (run infrastructure phase)"
    fi
    
    # Validate domain configuration
    if [ -z "$DOMAIN" ]; then
        error "DOMAIN environment variable is not set"
    fi
    
    # Show available backups for informational purposes
    list_certificate_backups
    
    # Manage certificates for the configured domain
    manage_certificates "$DOMAIN"
    
    # Show help information
    show_certificate_help
    
    success "Certificate management phase completed"
}

main "$@"