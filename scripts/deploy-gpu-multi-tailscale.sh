#!/bin/bash
# Deploy june-gpu-multi service on vast.ai with Tailscale integration
# 
# Usage: ./scripts/deploy-gpu-multi-tailscale.sh [vast_instance_id]
#
# Prerequisites:
# 1. Tailscale operator deployed in Kubernetes cluster
# 2. Services exposed via Tailscale annotations
# 3. Vast.ai instance with GPU support
# 4. Docker installed on vast.ai instance

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO_NAME="ozzuworld/june"
IMAGE_TAG="latest"
CONTAINER_NAME="june-gpu-multi"
TAILSCALE_HOSTNAME="june-gpu-$(date +%s)"

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running on vast.ai instance
check_vast_instance() {
    if ! nvidia-smi &> /dev/null; then
        print_warning "nvidia-smi not found. Make sure you're on a GPU instance."
    else
        print_success "GPU detected: $(nvidia-smi --query-gpu=name --format=csv,noheader,nounits)"
    fi
}

# Install Tailscale
install_tailscale() {
    print_info "Installing Tailscale..."
    
    if command -v tailscale &> /dev/null; then
        print_success "Tailscale already installed"
        return 0
    fi
    
    curl -fsSL https://tailscale.com/install.sh | sh
    
    if command -v tailscale &> /dev/null; then
        print_success "Tailscale installed successfully"
    else
        print_error "Failed to install Tailscale"
        exit 1
    fi
}

# Connect to Tailscale network
connect_tailscale() {
    print_info "Connecting to Tailscale network..."
    print_info "Please follow the authentication link that will be displayed"
    
    sudo tailscale up --hostname="$TAILSCALE_HOSTNAME"
    
    # Wait for connection
    sleep 5
    
    if tailscale status &> /dev/null; then
        print_success "Connected to Tailscale network"
        tailscale status
    else
        print_error "Failed to connect to Tailscale"
        exit 1
    fi
}

# Test connectivity to Kubernetes services
test_connectivity() {
    print_info "Testing connectivity to Kubernetes services..."
    
    # Test orchestrator
    if curl -s --connect-timeout 5 http://june-orchestrator:8080/healthz &> /dev/null; then
        print_success "✓ Orchestrator service reachable"
    else
        print_warning "✗ Orchestrator service not reachable (may take a few minutes to propagate)"
    fi
    
    # Test LiveKit
    if nc -z livekit 7880 2>/dev/null; then
        print_success "✓ LiveKit service reachable"
    else
        print_warning "✗ LiveKit service not reachable (may take a few minutes to propagate)"
    fi
}

# Pull and run the container
deploy_container() {
    print_info "Deploying june-gpu-multi container..."
    
    # Stop existing container if running
    if docker ps -a --format 'table {{.Names}}' | grep -q "$CONTAINER_NAME"; then
        print_info "Stopping existing container..."
        docker stop "$CONTAINER_NAME" || true
        docker rm "$CONTAINER_NAME" || true
    fi
    
    # Pull latest image
    print_info "Pulling latest image..."
    docker pull "$REPO_NAME/june-gpu-multi:$IMAGE_TAG"
    
    # Create environment file
    cat > .env << EOF
# Tailscale service endpoints
ORCHESTRATOR_URL=http://june-orchestrator:8080
LIVEKIT_WS_URL=ws://livekit:7880

# Service ports
STT_PORT=8001
TTS_PORT=8000

# GPU configuration
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16

# LiveKit configuration
ROOM_NAME=ozzu-main

# Add your credentials here:
# LIVEKIT_API_KEY=your_key_here
# LIVEKIT_API_SECRET=your_secret_here
# BEARER_TOKEN=your_token_here
EOF
    
    print_warning "Please edit .env file with your actual credentials:"
    print_info "nano .env"
    read -p "Press Enter after editing .env file..."
    
    # Run container
    print_info "Starting container..."
    docker run -d \
        --name "$CONTAINER_NAME" \
        --gpus all \
        --env-file .env \
        -p 8000:8000 \
        -p 8001:8001 \
        --restart unless-stopped \
        "$REPO_NAME/june-gpu-multi:$IMAGE_TAG"
    
    # Wait for container to start
    sleep 10
    
    # Check container status
    if docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -q "$CONTAINER_NAME.*Up"; then
        print_success "Container started successfully"
        docker logs --tail 20 "$CONTAINER_NAME"
    else
        print_error "Container failed to start"
        docker logs "$CONTAINER_NAME"
        exit 1
    fi
}

# Main deployment function
main() {
    print_info "Starting june-gpu-multi deployment with Tailscale integration"
    
    check_vast_instance
    install_tailscale
    connect_tailscale
    test_connectivity
    deploy_container
    
    print_success "Deployment completed!"
    print_info "Container status:"
    docker ps --filter "name=$CONTAINER_NAME" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    
    print_info "To check logs: docker logs -f $CONTAINER_NAME"
    print_info "To test services:"
    print_info "  - STT: curl http://localhost:8001/healthz"
    print_info "  - TTS: curl http://localhost:8000/healthz"
}

# Run main function
main "$@"