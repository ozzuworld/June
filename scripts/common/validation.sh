#!/bin/bash
# Common validation utilities for June Platform installation scripts

# Verify a command exists and is executable
verify_command() {
    local cmd="$1"
    local error_msg="$2"
    
    if ! command -v "$cmd" &> /dev/null; then
        error "${error_msg:-Command '$cmd' not found}"
    fi
}

# Verify a service is running
verify_service() {
    local service="$1"
    local error_msg="$2"
    
    if ! systemctl is-active --quiet "$service"; then
        error "${error_msg:-Service '$service' is not running}"
    fi
}

# Verify a port is open and listening
verify_port() {
    local port="$1"
    local error_msg="$2"
    
    if ! netstat -tlnp 2>/dev/null | grep -q ":$port "; then
        error "${error_msg:-Port '$port' is not listening}"
    fi
}

# Verify a kubernetes resource exists
verify_k8s_resource() {
    local resource_type="$1"
    local resource_name="$2"
    local namespace="${3:-default}"
    local error_msg="$4"
    
    if ! kubectl get "$resource_type" "$resource_name" -n "$namespace" &>/dev/null; then
        error "${error_msg:-Kubernetes resource '$resource_type/$resource_name' not found in namespace '$namespace'}"
    fi
}

# Verify kubernetes namespace exists
verify_namespace() {
    local namespace="$1"
    local error_msg="$2"
    
    if ! kubectl get namespace "$namespace" &>/dev/null; then
        error "${error_msg:-Kubernetes namespace '$namespace' not found}"
    fi
}

# Wait for kubernetes resource to be ready
wait_for_k8s_resource() {
    local resource_type="$1"
    local resource_name="$2"
    local condition="${3:-Ready}"
    local namespace="${4:-default}"
    local timeout="${5:-300}"
    local error_msg="$6"
    
    log "Waiting for $resource_type/$resource_name to be $condition in namespace $namespace..."
    
    if ! kubectl wait --for=condition="$condition" --timeout="${timeout}s" \
        "$resource_type/$resource_name" -n "$namespace" &>/dev/null; then
        error "${error_msg:-Timeout waiting for $resource_type/$resource_name to be $condition}"
    fi
}

# Wait for deployment to be available
wait_for_deployment() {
    local deployment="$1"
    local namespace="${2:-default}"
    local timeout="${3:-300}"
    
    wait_for_k8s_resource "deployment" "$deployment" "available" "$namespace" "$timeout" \
        "Timeout waiting for deployment '$deployment' to be available"
}

# Wait for pods to be ready
wait_for_pods() {
    local label_selector="$1"
    local namespace="${2:-default}"
    local timeout="${3:-300}"
    
    log "Waiting for pods with selector '$label_selector' to be ready in namespace '$namespace'..."
    
    if ! kubectl wait --for=condition=Ready --timeout="${timeout}s" \
        pod -l "$label_selector" -n "$namespace" &>/dev/null; then
        error "Timeout waiting for pods with selector '$label_selector' to be ready"
    fi
}

# Verify file exists and is readable
verify_file() {
    local file="$1"
    local error_msg="$2"
    
    if [ ! -f "$file" ]; then
        error "${error_msg:-File '$file' not found}"
    fi
    
    if [ ! -r "$file" ]; then
        error "${error_msg:-File '$file' is not readable}"
    fi
}

# Verify directory exists
verify_directory() {
    local dir="$1"
    local error_msg="$2"
    
    if [ ! -d "$dir" ]; then
        error "${error_msg:-Directory '$dir' not found}"
    fi
}

# Verify environment variable is set
verify_env_var() {
    local var_name="$1"
    local error_msg="$2"
    
    if [ -z "${!var_name}" ]; then
        error "${error_msg:-Environment variable '$var_name' is not set}"
    fi
}

# Verify URL is accessible
verify_url() {
    local url="$1"
    local expected_status="${2:-200}"
    local error_msg="$3"
    
    local status_code
    status_code=$(curl -s -o /dev/null -w "%{http_code}" "$url" || echo "000")
    
    if [ "$status_code" != "$expected_status" ]; then
        error "${error_msg:-URL '$url' returned status code $status_code, expected $expected_status}"
    fi
}

# Check if system has minimum requirements
check_system_requirements() {
    local min_ram_gb="${1:-4}"
    local min_disk_gb="${2:-20}"
    local min_cpu_cores="${3:-2}"
    
    # Check RAM
    local ram_gb
    ram_gb=$(free -g | awk '/^Mem:/{print $2}')
    if [ "$ram_gb" -lt "$min_ram_gb" ]; then
        error "System has ${ram_gb}GB RAM, minimum ${min_ram_gb}GB required"
    fi
    
    # Check disk space
    local disk_gb
    disk_gb=$(df / | awk 'NR==2 {print int($4/1024/1024)}')
    if [ "$disk_gb" -lt "$min_disk_gb" ]; then
        error "System has ${disk_gb}GB free disk space, minimum ${min_disk_gb}GB required"
    fi
    
    # Check CPU cores
    local cpu_cores
    cpu_cores=$(nproc)
    if [ "$cpu_cores" -lt "$min_cpu_cores" ]; then
        error "System has ${cpu_cores} CPU cores, minimum ${min_cpu_cores} required"
    fi
    
    success "System requirements check passed: ${ram_gb}GB RAM, ${disk_gb}GB disk, ${cpu_cores} CPU cores"
}

# Export all functions
export -f verify_command verify_service verify_port verify_k8s_resource verify_namespace
export -f wait_for_k8s_resource wait_for_deployment wait_for_pods verify_file verify_directory
export -f verify_env_var verify_url check_system_requirements