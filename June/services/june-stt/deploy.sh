#!/bin/bash
# June/services/june-stt/deploy.sh - External deployment script

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="june-stt"
IMAGE_NAME="june-stt:latest"
CONTAINER_NAME="june-stt-production"
NETWORK_NAME="june-network"

# Default values (override with environment variables)
EXTERNAL_PORT=${EXTERNAL_PORT:-8080}
METRICS_PORT=${METRICS_PORT:-9090}
WHISPER_MODEL=${WHISPER_MODEL:-large-v3}
WHISPER_DEVICE=${WHISPER_DEVICE:-auto}

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
    echo -e "${RED}[ERROR] $1${NC}"
    exit 1
}

warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

# Function to check required environment variables
check_env() {
    log "Checking required environment variables..."
    
    local required_vars=(
        "KEYCLOAK_URL"
        "KEYCLOAK_REALM" 
        "KEYCLOAK_CLIENT_ID"
        "KEYCLOAK_CLIENT_SECRET"
        "ORCHESTRATOR_URL"
        "EXTERNAL_STT_URL"
    )
    
    local missing_vars=()
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        error "Missing required environment variables: ${missing_vars[*]}"
    fi
    
    log "✅ All required environment variables are set"
}

# Function to check system requirements
check_system() {
    log "Checking system requirements..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed"
    fi
    
    # Check available memory (recommend at least 4GB)
    local mem_gb=$(free -g | awk '/^Mem:/{print $7}')
    if [[ $mem_gb -lt 4 ]]; then
        warning "Available memory is ${mem_gb}GB. Recommend at least 4GB for STT service"
    fi
    
    # Check disk space (recommend at least 10GB free)
    local disk_gb=$(df / | awk 'NR==2 {print int($4/1024/1024)}')
    if [[ $disk_gb -lt 10 ]]; then
        warning "Available disk space is ${disk_gb}GB. Recommend at least 10GB free"
    fi
    
    log "✅ System requirements check completed"
}

# Function to create Docker network
create_network() {
    log "Creating Docker network..."
    
    if ! docker network ls | grep -q "$NETWORK_NAME"; then
        docker network create "$NETWORK_NAME"
        log "✅ Created Docker network: $NETWORK_NAME"
    else
        info "Docker network already exists: $NETWORK_NAME"
    fi
}

# Function to build Docker image
build_image() {
    log "Building Docker image..."
    
    if [[ ! -f "Dockerfile" ]]; then
        error "Dockerfile not found. Run this script from the june-stt service directory"
    fi
    
    docker build -t "$IMAGE_NAME" .
    log "✅ Docker image built successfully: $IMAGE_NAME"
}

# Function to create volumes
create_volumes() {
    log "Creating Docker volumes for persistent data..."
    
    local volumes=(
        "june-stt-whisper-cache"
        "june-stt-huggingface-cache"
        "june-stt-logs"
    )
    
    for volume in "${volumes[@]}"; do
        if ! docker volume ls | grep -q "$volume"; then
            docker volume create "$volume"
            log "✅ Created volume: $volume"
        else
            info "Volume already exists: $volume"
        fi
    done
}

# Function to stop and remove existing container
cleanup_existing() {
    log "Cleaning up existing container..."
    
    if docker ps -a | grep -q "$CONTAINER_NAME"; then
        log "Stopping existing container..."
        docker stop "$CONTAINER_NAME" || true
        
        log "Removing existing container..."
        docker rm "$CONTAINER_NAME" || true
    fi
    
    log "✅ Cleanup completed"
}

# Function to deploy the service
deploy_service() {
    log "Deploying June STT service..."
    
    # Prepare environment file for container
    cat > .env.container << EOF
# Service Configuration
SERVICE_NAME=${SERVICE_NAME}
PORT=8080
HOST=0.0.0.0
EXTERNAL_STT_URL=${EXTERNAL_STT_URL}

# Keycloak Authentication
KEYCLOAK_URL=${KEYCLOAK_URL}
KEYCLOAK_REALM=${KEYCLOAK_REALM}
KEYCLOAK_CLIENT_ID=${KEYCLOAK_CLIENT_ID}
KEYCLOAK_CLIENT_SECRET=${KEYCLOAK_CLIENT_SECRET}
REQUIRED_AUDIENCE=${KEYCLOAK_CLIENT_ID}
JWKS_CACHE_TTL=300

# Orchestrator Integration
ORCHESTRATOR_URL=${ORCHESTRATOR_URL}
ENABLE_ORCHESTRATOR_NOTIFICATIONS=true
ORCHESTRATOR_WEBHOOK_PATH=/v1/stt/webhook

# Whisper Configuration
WHISPER_MODEL=${WHISPER_MODEL}
WHISPER_DEVICE=${WHISPER_DEVICE}
WHISPER_CACHE_DIR=/app/cache/whisper
HF_HOME=/app/cache/huggingface

# CORS Configuration
CORS_ALLOW_ORIGINS=${CORS_ALLOW_ORIGINS:-*}
CORS_ALLOW_METHODS=GET,POST,PUT,DELETE,OPTIONS
CORS_ALLOW_HEADERS=*
CORS_ALLOW_CREDENTIALS=true

# Performance & Limits
MAX_FILE_SIZE_MB=${MAX_FILE_SIZE_MB:-25}
MAX_DURATION_MINUTES=${MAX_DURATION_MINUTES:-30}
MAX_CONCURRENT_TRANSCRIPTIONS=${MAX_CONCURRENT_TRANSCRIPTIONS:-3}
TRANSCRIPT_RETENTION_HOURS=${TRANSCRIPT_RETENTION_HOURS:-24}

# Timeouts
HTTP_TIMEOUT_SECONDS=30
ORCHESTRATOR_TIMEOUT_SECONDS=10

# Logging
LOG_LEVEL=${LOG_LEVEL:-INFO}
LOG_FORMAT=json

# Monitoring
METRICS_ENABLED=true
METRICS_PORT=9090

# Security
RATE_LIMIT_REQUESTS_PER_MINUTE=${RATE_LIMIT_REQUESTS_PER_MINUTE:-100}
RATE_LIMIT_BURST_SIZE=20

# Networking
TRUST_PROXY_HEADERS=true
REAL_IP_HEADER=X-Forwarded-For
EOF

    # Run the container
    docker run -d \
        --name "$CONTAINER_NAME" \
        --network "$NETWORK_NAME" \
        --env-file .env.container \
        --restart unless-stopped \
        --memory="4g" \
        --cpus="2.0" \
        -p "${EXTERNAL_PORT}:8080" \
        -p "${METRICS_PORT}:9090" \
        -v june-stt-whisper-cache:/app/cache/whisper \
        -v june-stt-huggingface-cache:/app/cache/huggingface \
        -v june-stt-logs:/app/logs \
        --health-cmd="curl -f http://localhost:8080/healthz || exit 1" \
        --health-interval=30s \
        --health-timeout=15s \
        --health-start-period=120s \
        --health-retries=5 \
        "$IMAGE_NAME"
    
    # Clean up env file
    rm -f .env.container
    
    log "✅ June STT service deployed successfully"
}

# Function to wait for service to be ready
wait_for_service() {
    log "Waiting for service to be ready..."
    
    local max_attempts=40  # 2 minutes
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        if curl -sf "http://localhost:${EXTERNAL_PORT}/healthz" >/dev/null 2>&1; then
            log "✅ Service is ready and healthy"
            return 0
        fi
        
        echo -n "."
        sleep 3
        ((attempt++))
    done
    
    error "Service failed to become ready within timeout"
}

# Function to run post-deployment tests
run_tests() {
    log "Running post-deployment tests..."
    
    # Test 1: Health check
    info "Testing health check endpoint..."
    if ! curl -sf "http://localhost:${EXTERNAL_PORT}/healthz" | jq '.' >/dev/null 2>&1; then
        warning "Health check test failed"
    else
        log "✅ Health check test passed"
    fi
    
    # Test 2: Status endpoint
    info "Testing status endpoint..."
    if ! curl -sf "http://localhost:${EXTERNAL_PORT}/v1/status" | jq '.' >/dev/null 2>&1; then
        warning "Status endpoint test failed"
    else
        log "✅ Status endpoint test passed"
    fi
    
    # Test 3: Capabilities endpoint
    info "Testing capabilities endpoint..."
    if ! curl -sf "http://localhost:${EXTERNAL_PORT}/v1/capabilities" | jq '.' >/dev/null 2>&1; then
        warning "Capabilities endpoint test failed"
    else
        log "✅ Capabilities endpoint test passed"
    fi
    
    # Test 4: Connectivity test
    info "Testing external connectivity..."
    if ! curl -sf "http://localhost:${EXTERNAL_PORT}/v1/connectivity" | jq '.' >/dev/null 2>&1; then
        warning "Connectivity test failed"
    else
        log "✅ Connectivity test passed"
    fi
    
    # Test 5: Metrics endpoint (if enabled)
    if [[ "${METRICS_PORT}" != "disabled" ]]; then
        info "Testing metrics endpoint..."
        if ! curl -sf "http://localhost:${METRICS_PORT}/metrics" >/dev/null 2>&1; then
            warning "Metrics endpoint test failed"
        else
            log "✅ Metrics endpoint test passed"
        fi
    fi
}

# Function to display service information
show_service_info() {
    log "Deployment completed successfully!"
    echo ""
    echo "=== June STT Service Information ==="
    echo "Service URL: http://localhost:${EXTERNAL_PORT}"
    echo "External URL: ${EXTERNAL_STT_URL}"
    echo "Health Check: http://localhost:${EXTERNAL_PORT}/healthz"
    echo "Status: http://localhost:${EXTERNAL_PORT}/v1/status"
    echo "Capabilities: http://localhost:${EXTERNAL_PORT}/v1/capabilities"
    if [[ "${METRICS_PORT}" != "disabled" ]]; then
        echo "Metrics: http://localhost:${METRICS_PORT}/metrics"
    fi
    echo ""
    echo "=== Configuration ==="
    echo "Whisper Model: ${WHISPER_MODEL}"
    echo "Device: ${WHISPER_DEVICE}"
    echo "Keycloak: ${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}"
    echo "Orchestrator: ${ORCHESTRATOR_URL}"
    echo ""
    echo "=== Container Information ==="
    echo "Container Name: ${CONTAINER_NAME}"
    echo "Image: ${IMAGE_NAME}"
    echo "Network: ${NETWORK_NAME}"
    echo ""
    echo "=== Management Commands ==="
    echo "View logs: docker logs -f ${CONTAINER_NAME}"
    echo "Check status: docker ps | grep ${CONTAINER_NAME}"
    echo "Stop service: docker stop ${CONTAINER_NAME}"
    echo "Restart service: docker restart ${CONTAINER_NAME}"
    echo "Remove service: docker stop ${CONTAINER_NAME} && docker rm ${CONTAINER_NAME}"
    echo ""
}

# Function to show usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Deploy June STT service as external container"
    echo ""
    echo "Options:"
    echo "  --build-only       Only build the Docker image"
    echo "  --no-tests         Skip post-deployment tests"
    echo "  --force            Force rebuild and redeploy"
    echo "  --cleanup          Stop and remove existing container"
    echo "  --logs             Show container logs"
    echo "  --status           Show service status"
    echo "  --help             Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  KEYCLOAK_URL              Keycloak server URL (required)"
    echo "  KEYCLOAK_REALM            Keycloak realm (required)"
    echo "  KEYCLOAK_CLIENT_ID        Keycloak client ID (required)"
    echo "  KEYCLOAK_CLIENT_SECRET    Keycloak client secret (required)"
    echo "  ORCHESTRATOR_URL          Orchestrator service URL (required)"
    echo "  EXTERNAL_STT_URL          External URL for this STT service (required)"
    echo "  EXTERNAL_PORT             Port to expose (default: 8080)"
    echo "  WHISPER_MODEL             Whisper model to use (default: large-v3)"
    echo "  WHISPER_DEVICE            Device for Whisper (default: auto)"
    echo ""
}

# Main deployment function
main() {
    local build_only=false
    local no_tests=false
    local force=false
    local cleanup_only=false
    local show_logs=false
    local show_status=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --build-only)
                build_only=true
                shift
                ;;
            --no-tests)
                no_tests=true
                shift
                ;;
            --force)
                force=true
                shift
                ;;
            --cleanup)
                cleanup_only=true
                shift
                ;;
            --logs)
                show_logs=true
                shift
                ;;
            --status)
                show_status=true
                shift
                ;;
            --help)
                usage
                exit 0
                ;;
            *)
                error "Unknown option: $1. Use --help for usage information."
                ;;
        esac
    done
    
    # Handle special cases
    if [[ "$cleanup_only" == true ]]; then
        cleanup_existing
        exit 0
    fi
    
    if [[ "$show_logs" == true ]]; then
        docker logs -f "$CONTAINER_NAME" 2>/dev/null || error "Container not found: $CONTAINER_NAME"
        exit 0
    fi
    
    if [[ "$show_status" == true ]]; then
        docker ps | grep "$CONTAINER_NAME" || error "Container not found: $CONTAINER_NAME"
        echo ""
        curl -s "http://localhost:${EXTERNAL_PORT}/v1/status" | jq '.' 2>/dev/null || error "Service not responding"
        exit 0
    fi
    
    # Start deployment process
    log "Starting June STT External Deployment"
    log "====================================="
    
    # Pre-deployment checks
    check_system
    check_env
    
    # Build and deploy
    create_network
    create_volumes
    
    if [[ "$force" == true ]]; then
        cleanup_existing
    fi
    
    build_image
    
    if [[ "$build_only" == true ]]; then
        log "Build completed. Use --force to deploy."
        exit 0
    fi
    
    cleanup_existing
    deploy_service
    wait_for_service
    
    if [[ "$no_tests" == false ]]; then
        run_tests
    fi
    
    show_service_info
}

# Run main function with all arguments
main "$@"