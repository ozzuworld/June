#!/bin/bash
# Deploy june-gpu-multi service on vast.ai with optimized Tailscale integration
# 
# Usage: ./scripts/deploy-gpu-multi-tailscale.sh [vast_instance_id]
#
# Prerequisites:
# 1. Vast.ai instance with GPU support
# 2. Docker installed on vast.ai instance
# 3. TAILSCALE_AUTH_KEY environment variable for container
# Note: Tailscale is managed internally by the container

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

# Pull and run the container
deploy_container() {
    print_info "Deploying june-gpu-multi container with optimized networking..."
    
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
# Tailscale authentication (required)
TAILSCALE_AUTH_KEY=your_headscale_auth_key_here

# Service configuration
STT_PORT=8001
TTS_PORT=8000

# GPU configuration
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16

# LiveKit configuration (if using LiveKit)
ROOM_NAME=ozzu-main
# LIVEKIT_API_KEY=your_key_here
# LIVEKIT_API_SECRET=your_secret_here
# BEARER_TOKEN=your_token_here
EOF
    
    print_warning "Please edit .env file with your actual TAILSCALE_AUTH_KEY and other credentials:"
    print_info "nano .env"
    read -p "Press Enter after editing .env file..."
    
    # Validate required environment variables
    if ! grep -q "TAILSCALE_AUTH_KEY=.*[^[:space:]]" .env; then
        print_error "TAILSCALE_AUTH_KEY is required in .env file"
        exit 1
    fi
    
    # Run container with optimized configuration
    print_info "Starting container with direct Tailscale networking..."
    docker run -d \
        --name "$CONTAINER_NAME" \
        --gpus all \
        --env-file .env \
        -p 8000:8000 \
        -p 8001:8001 \
        --restart unless-stopped \
        "$REPO_NAME/june-gpu-multi:$IMAGE_TAG"
    
    # Wait for container to start and connect to Tailscale
    print_info "Waiting for container startup and Tailscale connection..."
    sleep 15
    
    # Check container status
    if docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -q "$CONTAINER_NAME.*Up"; then
        print_success "Container started successfully"
        
        # Show recent logs to verify Tailscale connection
        print_info "Recent container logs:"
        docker logs --tail 30 "$CONTAINER_NAME"
        
        # Test service health
        sleep 10
        print_info "Testing service health..."
        if curl -s --max-time 5 http://localhost:8000/healthz >/dev/null 2>&1; then
            print_success "✓ TTS service is healthy"
        else
            print_warning "✗ TTS service not ready yet (may need more time)"
        fi
        
        if curl -s --max-time 5 http://localhost:8001/healthz >/dev/null 2>&1; then
            print_success "✓ STT service is healthy"
        else
            print_warning "✗ STT service not ready yet (may need more time)"
        fi
        
    else
        print_error "Container failed to start"
        docker logs "$CONTAINER_NAME"
        exit 1
    fi
}

# Main deployment function
main() {
    print_info "Starting optimized june-gpu-multi deployment"
    print_info "Tailscale networking is managed internally by the container"
    
    check_vast_instance
    deploy_container
    
    print_success "Deployment completed!"
    print_info "Container status:"
    docker ps --filter "name=$CONTAINER_NAME" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    
    print_info "Useful commands:"
    print_info "  - Check logs: docker logs -f $CONTAINER_NAME"
    print_info "  - Test STT: curl http://localhost:8001/healthz"
    print_info "  - Test TTS: curl http://localhost:8000/healthz"
    print_info "  - Check Tailscale status: docker exec $CONTAINER_NAME tailscale status"
}

# Run main function
main "$@"