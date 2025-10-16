#!/bin/bash
# June Platform - Phase 10: Final Setup and Verification
# Performs final configuration and comprehensive system verification

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

# Source configuration from environment or config file
if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
fi

setup_additional_reference_grants() {
    log "Setting up additional ReferenceGrants..."
    
    # Ensure ReferenceGrant for STUNner to june-services namespace exists
    cat <<EOF | kubectl apply -f - > /dev/null 2>&1
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: stunner-to-june-services
  namespace: june-services
spec:
  from:
  - group: stunner.l7mp.io
    kind: UDPRoute
    namespace: stunner
  to:
  - group: ""
    kind: Service
EOF
    
    success "ReferenceGrants configured"
}

verify_certificates() {
    log "Verifying SSL certificates..."
    
    if [ -z "$DOMAIN" ]; then
        warn "DOMAIN not set, skipping certificate verification"
        return 0
    fi
    
    # Check if certificates are being issued
    log "Checking certificate requests..."
    if kubectl get certificates -A &>/dev/null; then
        kubectl get certificates -A
    else
        log "No certificates found yet"
    fi
    
    # Check certificate issuers
    if kubectl get clusterissuer letsencrypt-prod &>/dev/null; then
        success "Let's Encrypt ClusterIssuer configured"
    else
        warn "Let's Encrypt ClusterIssuer not found"
    fi
    
    # Check certificate backups
    if [ -d "/root/.june-certs" ]; then
        local backup_count
        backup_count=$(find /root/.june-certs -name "*-wildcard-tls-backup.yaml" | wc -l)
        if [ "$backup_count" -gt 0 ]; then
            success "Certificate backups found: $backup_count"
        else
            log "No certificate backups found yet"
        fi
    fi
}

verify_networking() {
    log "Verifying networking configuration..."
    
    # Check ingress-nginx
    if kubectl get pods -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --no-headers | grep -q Running; then
        success "Ingress controller is running"
    else
        warn "Ingress controller not running properly"
    fi
    
    # Check STUNner gateway
    if kubectl get gateway stunner-gateway -n stunner &>/dev/null; then
        success "STUNner gateway configured"
        kubectl get gateway stunner-gateway -n stunner -o wide
    else
        warn "STUNner gateway not found"
    fi
    
    # Check UDPRoute
    if kubectl get udproute -n stunner &>/dev/null; then
        log "UDPRoutes configured:"
        kubectl get udproute -n stunner
    else
        log "No UDPRoutes found"
    fi
}

get_system_info() {
    log "Gathering system information..."
    
    # Get external IP
    local external_ip
    external_ip=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    
    # Get internal IP
    local internal_ip
    internal_ip=$(hostname -I | awk '{print $1}')
    
    # Check GPU availability
    local gpu_available="false"
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        gpu_available="true"
    fi
    
    # Store system info in variables for final report
    echo "$external_ip" > /tmp/june_external_ip
    echo "$internal_ip" > /tmp/june_internal_ip
    echo "$gpu_available" > /tmp/june_gpu_available
    
    log "System Information:"
    log "  External IP: $external_ip"
    log "  Internal IP: $internal_ip"
    log "  GPU Available: $gpu_available"
}

run_system_health_check() {
    log "Running system health check..."
    
    local health_issues=0
    
    # Check Kubernetes cluster health
    if ! kubectl cluster-info &>/dev/null; then
        error "Kubernetes cluster is not healthy"
        ((health_issues++))
    fi
    
    # Check core namespaces
    local namespaces=("kube-system" "ingress-nginx" "cert-manager" "june-services" "media" "stunner" "stunner-system")
    for ns in "${namespaces[@]}"; do
        if ! kubectl get namespace "$ns" &>/dev/null; then
            warn "Namespace $ns not found"
            ((health_issues++))
        fi
    done
    
    # Check critical pods are running
    local critical_pods=0
    local total_pods=0
    
    for ns in "${namespaces[@]}"; do
        if kubectl get namespace "$ns" &>/dev/null; then
            local pod_count
            pod_count=$(kubectl get pods -n "$ns" --no-headers 2>/dev/null | wc -l)
            local running_count
            running_count=$(kubectl get pods -n "$ns" --no-headers 2>/dev/null | grep -c "Running" || echo "0")
            
            total_pods=$((total_pods + pod_count))
            critical_pods=$((critical_pods + running_count))
            
            if [ "$pod_count" -gt 0 ]; then
                log "  $ns: $running_count/$pod_count pods running"
            fi
        fi
    done
    
    if [ "$total_pods" -gt 0 ] && [ "$critical_pods" -eq "$total_pods" ]; then
        success "All pods are running ($critical_pods/$total_pods)"
    else
        warn "Some pods are not running ($critical_pods/$total_pods)"
        ((health_issues++))
    fi
    
    if [ "$health_issues" -eq 0 ]; then
        success "System health check passed"
    else
        warn "System health check found $health_issues issues"
    fi
    
    return "$health_issues"
}

generate_final_report() {
    log "Generating final installation report..."
    
    # Read system info from temp files
    local external_ip internal_ip gpu_available
    external_ip=$(cat /tmp/june_external_ip 2>/dev/null || echo "unknown")
    internal_ip=$(cat /tmp/june_internal_ip 2>/dev/null || echo "unknown")
    gpu_available=$(cat /tmp/june_gpu_available 2>/dev/null || echo "false")
    
    # Clean up temp files
    rm -f /tmp/june_external_ip /tmp/june_internal_ip /tmp/june_gpu_available
    
    echo ""
    echo "==========================================="
    success "June Platform Installation Complete!"
    echo "==========================================="
    echo ""
    echo "📋 Your Services:"
    echo "  API:        https://api.${DOMAIN:-your-domain.com}"
    echo "  Identity:   https://idp.${DOMAIN:-your-domain.com}"
    if [ "$gpu_available" = "true" ]; then
        echo "  STT:        https://stt.${DOMAIN:-your-domain.com}"
        echo "  TTS:        https://tts.${DOMAIN:-your-domain.com}"
    fi
    echo ""
    echo "🎮 WebRTC Services:"
    echo "  LiveKit:    livekit.media.svc.cluster.local"
    echo "  TURN:       turn:${external_ip}:3478"
    echo ""
    echo "🌐 DNS Configuration:"
    echo "  Point these records to: $external_ip"
    echo "    ${DOMAIN:-your-domain.com}           A    $external_ip"
    echo "    *.${DOMAIN:-your-domain.com}         A    $external_ip"
    echo ""
    echo "🔐 Access Credentials:"
    echo "  Keycloak Admin: https://idp.${DOMAIN:-your-domain.com}/admin"
    echo "    Username: admin"
    echo "    Password: ${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}"
    echo ""
    echo "  TURN Server: turn:${external_ip}:3478"
    echo "    Username: ${TURN_USERNAME:-june-user}"
    echo "    Password: ${STUNNER_PASSWORD:-Pokemon123!}"
    echo ""
    echo "🔒 Certificate Management:"
    echo "  Backup Directory: /root/.june-certs/"
    if [ -n "$DOMAIN" ]; then
        echo "  Current Certificate: ${DOMAIN//\./-}-wildcard-tls"
        echo "  Backup File: /root/.june-certs/${DOMAIN}-wildcard-tls-backup.yaml"
    fi
    echo ""
    echo "📊 Status Commands:"
    echo "  kubectl get pods -n june-services   # Core services"
    echo "  kubectl get pods -n media            # LiveKit"
    echo "  kubectl get gateway -n stunner       # STUNner"
    echo "  kubectl get certificates -A          # SSL certificates"
    echo "  ls -la /root/.june-certs/            # Certificate backups"
    echo ""
    echo "🔧 Troubleshooting:"
    echo "  kubectl logs -n june-services deployment/june-orchestrator"
    echo "  kubectl describe gateway stunner-gateway -n stunner"
    echo "  kubectl get events --sort-by='.lastTimestamp' -A"
    echo "  kubectl describe certificate -n june-services"
    echo ""
    echo "==========================================="
}

cleanup_installation() {
    log "Cleaning up installation artifacts..."
    
    # Remove temporary files if any
    rm -f /tmp/june_* 2>/dev/null || true
    
    # Clean up package cache
    apt-get autoremove -y > /dev/null 2>&1 || true
    apt-get autoclean > /dev/null 2>&1 || true
    
    success "Installation cleanup completed"
}

# Main execution
main() {
    log "Starting final setup and verification phase..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "This script must be run as root"
    fi
    
    # Verify prerequisites
    verify_command "kubectl" "kubectl must be available"
    
    if ! kubectl cluster-info &> /dev/null; then
        error "Kubernetes cluster must be running"
    fi
    
    setup_additional_reference_grants
    verify_certificates
    verify_networking
    get_system_info
    
    # Run health check
    if run_system_health_check; then
        log "System is healthy, proceeding with final report"
    else
        warn "System health check detected issues, but continuing"
    fi
    
    cleanup_installation
    generate_final_report
    
    success "Final setup and verification phase completed"
}

main "$@"