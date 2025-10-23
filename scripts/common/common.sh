#!/bin/bash
# Common utilities for June Platform installation scripts

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

# Logging functions
log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

# Utility functions
check_command() {
    local cmd="$1"
    local install_msg="${2:-Please install $cmd}"
    
    if ! command -v "$cmd" &> /dev/null; then
        error "$cmd is not installed. $install_msg"
    fi
}

check_kubernetes() {
    check_command kubectl "Please install kubectl"
    if ! kubectl cluster-info &>/dev/null; then
        error "Cannot connect to Kubernetes cluster"
    fi
}

wait_for_pods() {
    local namespace="$1"
    local selector="$2"
    local timeout="${3:-300}"
    
    log "Waiting for pods in namespace $namespace with selector $selector..."
    if ! kubectl wait --for=condition=ready --timeout="${timeout}s" pods -n "$namespace" -l "$selector"; then
        warn "Pods not ready after ${timeout} seconds"
        kubectl get pods -n "$namespace" -l "$selector"
        return 1
    fi
}

wait_for_deployment() {
    local namespace="$1"
    local deployment="$2"
    local timeout="${3:-300}"
    
    log "Waiting for deployment $deployment in namespace $namespace..."
    if ! kubectl wait --for=condition=available --timeout="${timeout}s" deployment/"$deployment" -n "$namespace"; then
        warn "Deployment $deployment not available after ${timeout} seconds"
        kubectl get deployment "$deployment" -n "$namespace"
        kubectl describe deployment "$deployment" -n "$namespace"
        return 1
    fi
}

check_namespace() {
    local namespace="$1"
    if ! kubectl get namespace "$namespace" &>/dev/null; then
        log "Creating namespace: $namespace"
        kubectl create namespace "$namespace"
    fi
}

# Source existing common scripts if they exist
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/logging.sh" ]; then
    source "$SCRIPT_DIR/logging.sh"
fi
if [ -f "$SCRIPT_DIR/validation.sh" ]; then
    source "$SCRIPT_DIR/validation.sh"
fi