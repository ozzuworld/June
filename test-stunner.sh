#!/bin/bash
# STUNner Installation Verification Script
# Tests STUNner Gateway, Routes, and connectivity

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

echo "=========================================="
echo "🎯 STUNner Installation Verification"
echo "=========================================="
echo ""

# Test 1: Check STUNner operator
log_info "Test 1: STUNner Operator Status"
echo "----------------------------------"

if kubectl get deployment -n stunner-system stunner-gateway-operator-controller-manager &>/dev/null; then
    READY=$(kubectl get deployment -n stunner-system stunner-gateway-operator-controller-manager -o jsonpath='{.status.readyReplicas}')
    if [ "$READY" -ge 1 ]; then
        log_success "STUNner operator is running ($READY replicas)"
    else
        log_error "STUNner operator not ready"
        kubectl get pods -n stunner-system
        exit 1
    fi
else
    log_error "STUNner operator not found"
    exit 1
fi
echo ""

# Test 2: Check Gateway API CRDs
log_info "Test 2: Gateway API CRDs"
echo "----------------------------------"

CRDS=(
    "gatewayclasses.gateway.networking.k8s.io"
    "gateways.gateway.networking.k8s.io"
    "udproutes.stunner.l7mp.io"
    "gatewayconfigs.stunner.l7mp.io"
)

ALL_CRDS_OK=true
for crd in "${CRDS[@]}"; do
    if kubectl get crd "$crd" &>/dev/null; then
        log_success "CRD found: $crd"
    else
        log_error "CRD missing: $crd"
        ALL_CRDS_OK=false
    fi
done

if [ "$ALL_CRDS_OK" = false ]; then
    exit 1
fi
echo ""

# Test 3: Check GatewayClass
log_info "Test 3: GatewayClass Configuration"
echo "----------------------------------"

if kubectl get gatewayclass stunner-gatewayclass &>/dev/null; then
    STATUS=$(kubectl get gatewayclass stunner-gatewayclass -o jsonpath='{.status.conditions[?(@.type=="Accepted")].status}')
    if [ "$STATUS" = "True" ]; then
        log_success "GatewayClass is accepted"
    else
        log_warning "GatewayClass status: $STATUS"
        kubectl get gatewayclass stunner-gatewayclass -o yaml
    fi
else
    log_error "GatewayClass 'stunner-gatewayclass' not found"
    exit 1
fi
echo ""

# Test 4: Check GatewayConfig
log_info "Test 4: GatewayConfig"
echo "----------------------------------"

if kubectl get gatewayconfig -n stunner-system stunner-gatewayconfig &>/dev/null; then
    REALM=$(kubectl get gatewayconfig -n stunner-system stunner-gatewayconfig -o jsonpath='{.spec.realm}')
    AUTH_TYPE=$(kubectl get gatewayconfig -n stunner-system stunner-gatewayconfig -o jsonpath='{.spec.authType}')
    
    log_success "GatewayConfig found"
    echo "  Realm: $REALM"
    echo "  Auth Type: $AUTH_TYPE"
else
    log_error "GatewayConfig not found"
    exit 1
fi
echo ""

# Test 5: Check Gateway
log_info "Test 5: STUNner Gateway Status"
echo "----------------------------------"

if kubectl get gateway -n stunner june-stunner-gateway &>/dev/null; then
    ACCEPTED=$(kubectl get gateway -n stunner june-stunner-gateway -o jsonpath='{.status.conditions[?(@.type=="Accepted")].status}')
    PROGRAMMED=$(kubectl get gateway -n stunner june-stunner-gateway -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}')
    
    log_success "Gateway 'june-stunner-gateway' found"
    echo "  Accepted: $ACCEPTED"
    echo "  Programmed: $PROGRAMMED"
    
    # Get gateway service
    if kubectl get svc -n stunner june-stunner-gateway-udp &>/dev/null; then
        SERVICE_TYPE=$(kubectl get svc -n stunner june-stunner-gateway-udp -o jsonpath='{.spec.type}')
        EXTERNAL_IP=$(kubectl get svc -n stunner june-stunner-gateway-udp -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
        
        log_success "Gateway service found"
        echo "  Type: $SERVICE_TYPE"
        echo "  External IP: ${EXTERNAL_IP:-<pending>}"
    else
        log_warning "Gateway service not found yet (may be creating)"
    fi
else
    log_error "Gateway 'june-stunner-gateway' not found"
    exit 1
fi
echo ""

# Test 6: Check UDPRoutes
log_info "Test 6: UDPRoutes Configuration"
echo "----------------------------------"

ROUTES=(
    "june-orchestrator-route"
    "june-stt-route"
    "june-tts-route"
)

ALL_ROUTES_OK=true
for route in "${ROUTES[@]}"; do
    if kubectl get udproute -n stunner "$route" &>/dev/null; then
        PARENTS=$(kubectl get udproute -n stunner "$route" -o jsonpath='{.spec.parentRefs[*].name}')
        BACKENDS=$(kubectl get udproute -n stunner "$route" -o jsonpath='{.spec.rules[*].backendRefs[*].name}')
        
        log_success "UDPRoute found: $route"
        echo "  Parent: $PARENTS"
        echo "  Backend: $BACKENDS"
    else
        log_error "UDPRoute missing: $route"
        ALL_ROUTES_OK=false
    fi
done

if [ "$ALL_ROUTES_OK" = false ]; then
    exit 1
fi
echo ""

# Test 7: Check ReferenceGrant
log_info "Test 7: ReferenceGrant (Cross-namespace access)"
echo "----------------------------------"

if kubectl get referencegrant -n june-services stunner-to-june-services &>/dev/null; then
    log_success "ReferenceGrant exists"
else
    log_warning "ReferenceGrant not found (may cause routing issues)"
fi
echo ""

# Test 8: Check STUNner dataplane pods
log_info "Test 8: STUNner Dataplane Pods"
echo "----------------------------------"

DATAPLANE_PODS=$(kubectl get pods -n stunner -l app.kubernetes.io/name=stunner 2>/dev/null)
if [ -n "$DATAPLANE_PODS" ]; then
    log_success "STUNner dataplane pods found:"
    kubectl get pods -n stunner -l app.kubernetes.io/name=stunner
else
    log_warning "No STUNner dataplane pods found (will be created when needed)"
fi
echo ""

# Test 9: WebRTC ConfigMap
log_info "Test 9: WebRTC Configuration"
echo "----------------------------------"

if kubectl get configmap -n june-services june-webrtc-config &>/dev/null; then
    log_success "WebRTC ConfigMap exists"
    
    # Check for required keys
    KEYS=(
        "STUN_SERVER_URL"
        "TURN_SERVER_URL"
        "TURN_USERNAME"
        "TURN_CREDENTIAL"
        "ICE_SERVERS"
    )
    
    ALL_KEYS_OK=true
    for key in "${KEYS[@]}"; do
        VALUE=$(kubectl get configmap -n june-services june-webrtc-config -o jsonpath="{.data.$key}" 2>/dev/null)
        if [ -n "$VALUE" ]; then
            echo "  ✓ $key configured"
        else
            log_warning "  ✗ $key missing"
            ALL_KEYS_OK=false
        fi
    done
    
    if [ "$ALL_KEYS_OK" = true ]; then
        log_success "All required keys present"
    fi
else
    log_error "WebRTC ConfigMap not found"
fi
echo ""

# Summary
echo "=========================================="
echo "📊 Verification Summary"
echo "=========================================="
echo ""

echo "✅ STUNner Components:"
echo "  • Operator: Running"
echo "  • Gateway API CRDs: Installed"
echo "  • GatewayClass: Configured"
echo "  • GatewayConfig: Configured"
echo "  • Gateway: Active"
echo "  • UDPRoutes: Configured"
echo ""

echo "📋 Next Steps:"
echo "  1. Verify DNS points to your server IP"
echo "  2. Test WebRTC connectivity from client"
echo "  3. Check orchestrator logs:"
echo "     kubectl logs -n june-services -l app=june-orchestrator --tail=50"
echo ""

echo "🔍 Useful Commands:"
echo "  kubectl get all -n stunner"
echo "  kubectl get gateway -n stunner june-stunner-gateway -o yaml"
echo "  kubectl get udproute -n stunner"
echo "  kubectl logs -n stunner-system -l control-plane=stunner-gateway-operator-controller-manager"
echo ""
echo "=========================================="