#!/bin/bash
# test-deployment.sh
# Comprehensive testing script for June AI Platform

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }

# Configuration
NAMESPACE="june-services"
BASE_URL="${BASE_URL:-https://june-orchestrator.allsafe.world}"
KEYCLOAK_URL="${KEYCLOAK_URL:-https://june-idp.allsafe.world/auth}"

# Test cluster connectivity
test_cluster_connectivity() {
    log "🔗 Testing Kubernetes cluster connectivity..."
    
    if kubectl cluster-info >/dev/null 2>&1; then
        success "Cluster connectivity OK"
    else
        error "Cannot connect to Kubernetes cluster"
    fi
    
    # Check namespace exists
    if kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
        success "Namespace '$NAMESPACE' exists"
    else
        error "Namespace '$NAMESPACE' not found"
    fi
}

# Test pod status
test_pod_status() {
    log "🏃 Testing pod status..."
    
    services=("june-idp" "june-orchestrator" "june-stt" "june-tts")
    
    for service in "${services[@]}"; do
        log "Checking $service pods..."
        
        pod_status=$(kubectl get pods -n "$NAMESPACE" -l app="$service" -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
        
        if [[ "$pod_status" == "Running" ]]; then
            success "$service pod is running"
        else
            warning "$service pod status: $pod_status"
        fi
        
        # Check ready status
        ready_status=$(kubectl get pods -n "$NAMESPACE" -l app="$service" -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
        
        if [[ "$ready_status" == "True" ]]; then
            success "$service pod is ready"
        else
            warning "$service pod ready status: $ready_status"
        fi
    done
}

# Test service endpoints
test_service_endpoints() {
    log "🌐 Testing service endpoints..."
    
    services=("june-idp" "june-orchestrator" "june-stt" "june-tts")
    
    for service in "${services[@]}"; do
        log "Testing $service endpoint..."
        
        # Port forward to test locally
        kubectl port-forward -n "$NAMESPACE" "service/$service" 8080:8080 &
        pf_pid=$!
        sleep 3
        
        # Test health endpoint
        if curl -f -s http://localhost:8080/healthz >/dev/null 2>&1; then
            success "$service health endpoint OK"
        else
            warning "$service health endpoint failed"
        fi
        
        # Test root endpoint
        if curl -f -s http://localhost:8080/ >/dev/null 2>&1; then
            success "$service root endpoint OK"
        else
            warning "$service root endpoint failed"
        fi
        
        # Cleanup port forward
        kill $pf_pid 2>/dev/null || true
        sleep 2
    done
}

# Test Keycloak admin access
test_keycloak_admin() {
    log "🔑 Testing Keycloak admin access..."
    
    # Port forward to Keycloak
    kubectl port-forward -n "$NAMESPACE" service/june-idp 8080:8080 &
    pf_pid=$!
    sleep 5
    
    # Test Keycloak health
    if curl -f -s http://localhost:8080/auth/health >/dev/null 2>&1; then
        success "Keycloak health endpoint OK"
    else
        warning "Keycloak health endpoint failed"
    fi
    
    # Test realm endpoint
    if curl -f -s http://localhost:8080/auth/realms/june >/dev/null 2>&1; then
        success "June realm accessible"
    else
        warning "June realm not accessible"
    fi
    
    # Test OIDC configuration endpoint
    if curl -f -s http://localhost:8080/auth/realms/june/.well-known/openid_configuration >/dev/null 2>&1; then
        success "OIDC configuration endpoint OK"
    else
        warning "OIDC configuration endpoint failed"
    fi
    
    kill $pf_pid 2>/dev/null || true
    sleep 2
}

# Test service-to-service authentication
test_service_auth() {
    log "🔐 Testing service-to-service authentication..."
    
    # Port forward to Keycloak
    kubectl port-forward -n "$NAMESPACE" service/june-idp 8080:8080 &
    kc_pid=$!
    sleep 5
    
    # Get token for orchestrator service
    log "Getting token for orchestrator service..."
    
    token_response=$(curl -s -X POST \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=client_credentials" \
        -d "client_id=orchestrator-client" \
        -d "client_secret=orchestrator-secret-key-12345" \
        http://localhost:8080/auth/realms/june/protocol/openid-connect/token 2>/dev/null || echo '{}')
    
    access_token=$(echo "$token_response" | jq -r '.access_token // empty' 2>/dev/null || echo "")
    
    if [[ -n "$access_token" && "$access_token" != "null" ]]; then
        success "Service authentication token obtained"
        
        # Test token with STT service
        kubectl port-forward -n "$NAMESPACE" service/june-stt 8081:8080 &
        stt_pid=$!
        sleep 3
        
        if curl -f -s -H "Authorization: Bearer $access_token" http://localhost:8081/v1/test-auth >/dev/null 2>&1; then
            success "Service-to-service authentication working"
        else
            warning "Service-to-service authentication failed"
        fi
        
        kill $stt_pid 2>/dev/null || true
    else
        warning "Failed to obtain service authentication token"
    fi
    
    kill $kc_pid 2>/dev/null || true
    sleep 2
}

# Test external connectivity (if DNS is configured)
test_external_connectivity() {
    log "🌍 Testing external connectivity..."
    
    if [[ "$BASE_URL" == *"localhost"* ]]; then
        warning "Skipping external connectivity test (localhost URL)"
        return
    fi
    
    # Test Keycloak external access
    if curl -f -s --connect-timeout 10 "$KEYCLOAK_URL/realms/june" >/dev/null 2>&1; then
        success "Keycloak externally accessible"
    else
        warning "Keycloak not externally accessible (DNS/ingress may not be ready)"
    fi
    
    # Test orchestrator external access
    if curl -f -s --connect-timeout 10 "$BASE_URL/healthz" >/dev/null 2>&1; then
        success "Orchestrator externally accessible"
    else
        warning "Orchestrator not externally accessible (DNS/ingress may not be ready)"
    fi
}

# Test AI integration
test_ai_integration() {
    log "🤖 Testing AI integration..."
    
    # Port forward to orchestrator
    kubectl port-forward -n "$NAMESPACE" service/june-orchestrator 8080:8080 &
    orch_pid=$!
    sleep 3
    
    # Check AI configuration
    config_response=$(curl -s http://localhost:8080/configz 2>/dev/null || echo '{}')
    
    ai_enabled=$(echo "$config_response" | jq -r '.ai_model_enabled // false' 2>/dev/null || echo "false")
    gemini_key_present=$(echo "$config_response" | jq -r '.gemini_api_key_present // false' 2>/dev/null || echo "false")
    
    if [[ "$ai_enabled" == "true" ]]; then
        success "AI model enabled"
    else
        warning "AI model not enabled"
    fi
    
    if [[ "$gemini_key_present" == "true" ]]; then
        success "Gemini API key configured"
    else
        warning "Gemini API key not configured"
    fi
    
    kill $orch_pid 2>/dev/null || true
    sleep 2
}

# Test complete workflow
test_complete_workflow() {
    log "🔄 Testing complete AI workflow..."
    
    # This would require more complex setup with actual audio files
    # For now, just test the endpoint availability
    
    kubectl port-forward -n "$NAMESPACE" service/june-orchestrator 8080:8080 &
    orch_pid=$!
    sleep 3
    
    # Test chat endpoint (if service auth is working)
    # This is a simplified test
    if curl -f -s http://localhost:8080/ >/dev/null 2>&1; then
        success "Orchestrator API endpoints accessible"
    else
        warning "Orchestrator API endpoints not accessible"
    fi
    
    kill $orch_pid 2>/dev/null || true
    sleep 2
}

# Generate test report
generate_report() {
    log "📊 Generating test report..."
    
    echo ""
    echo "==================== JUNE AI PLATFORM TEST REPORT ===================="
    echo ""
    echo "Test Date: $(date)"
    echo "Cluster: $(kubectl config current-context 2>/dev/null || echo 'Unknown')"
    echo "Namespace: $NAMESPACE"
    echo ""
    
    # Pod status summary
    echo "Pod Status Summary:"
    kubectl get pods -n "$NAMESPACE" -o wide 2>/dev/null || echo "Failed to get pod status"
    echo ""
    
    # Service status summary
    echo "Service Status Summary:"
    kubectl get services -n "$NAMESPACE" 2>/dev/null || echo "Failed to get service status"
    echo ""
    
    # Ingress status
    echo "Ingress Status:"
    kubectl get ingress -n "$NAMESPACE" 2>/dev/null || echo "Failed to get ingress status"
    echo ""
    
    # Recent events
    echo "Recent Events:"
    kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' | tail -10 2>/dev/null || echo "Failed to get events"
    echo ""
    
    echo "======================================================================="
}

# Main test function
main() {
    log "🧪 Starting June AI Platform testing..."
    
    # Check if jq is available (needed for JSON parsing)
    if ! command -v jq >/dev/null 2>&1; then
        warning "jq not found - some tests may be limited"
    fi
    
    test_cluster_connectivity
    test_pod_status
    test_service_endpoints
    test_keycloak_admin
    test_service_auth
    test_external_connectivity
    test_ai_integration
    test_complete_workflow
    generate_report
    
    success "Testing completed! Check the report above for details."
    
    echo ""
    echo "🔧 Next Steps:"
    echo "  1. Fix any warnings shown above"
    echo "  2. Configure DNS if external access failed"
    echo "  3. Update API keys if AI integration warnings appeared"
    echo "  4. Change default Keycloak admin password"
}

# Run main function
main "$@"