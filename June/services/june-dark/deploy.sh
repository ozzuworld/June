#!/bin/bash

# June Dark OSINT Framework Deployment Script
# Usage: ./deploy.sh [build|run|stop|logs|status]

set -e

# Configuration
IMAGE_NAME="june-dark"
TAG="latest"
CONTAINER_NAME="june-dark-osint"
PORT="9009"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_blue() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

check_requirements() {
    log_info "Checking system requirements..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    # Check nvidia-docker for GPU support
    if ! docker info | grep -q "nvidia"; then
        log_warn "NVIDIA Docker runtime not detected. GPU acceleration will not be available."
        GPU_SUPPORT=false
    else
        log_info "NVIDIA Docker runtime detected. GPU acceleration available."
        GPU_SUPPORT=true
    fi
    
    # Check if .env file exists
    if [ ! -f ".env" ]; then
        log_warn ".env file not found. Creating template..."
        create_env_template
    fi
}

create_env_template() {
    cat > .env << EOF
# June Dark OSINT Framework Configuration

# OpenCTI Configuration (Required for threat intelligence)
OPENCTI_URL=http://localhost:8080
OPENCTI_TOKEN=your-opencti-api-token-here
OPENCTI_SSL_VERIFY=true

# YOLO Configuration
YOLO_MODEL_SIZE=small
YOLO_CONFIDENCE=0.4
YOLO_IOU_THRESHOLD=0.7

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# RabbitMQ Configuration
RABBIT_URL=amqp://guest:guest@localhost:5672//

# GPU Configuration
CUDA_VISIBLE_DEVICES=0
GPU_MEMORY_FRACTION=0.8

# Logging
LOG_LEVEL=INFO
EOF
    log_info "Created .env template. Please edit it with your configuration."
}

build_image() {
    log_info "Building June Dark OSINT Framework..."
    
    # Build with appropriate Dockerfile
    if [ "$GPU_SUPPORT" = true ]; then
        log_info "Building with GPU support..."
        docker build -f Dockerfile.gpu -t ${IMAGE_NAME}:${TAG} .
    else
        log_warn "Building CPU-only version..."
        # Create CPU Dockerfile if it doesn't exist
        if [ ! -f "Dockerfile.cpu" ]; then
            log_info "Creating CPU Dockerfile..."
            sed 's/nvidia\/cuda:12.1.1-cudnn8-runtime-ubuntu22.04/ubuntu:22.04/g' Dockerfile.gpu > Dockerfile.cpu
            sed -i 's/faiss-gpu/faiss-cpu/g' Dockerfile.cpu
            sed -i 's/onnxruntime-gpu/onnxruntime/g' Dockerfile.cpu
        fi
        docker build -f Dockerfile.cpu -t ${IMAGE_NAME}:${TAG} .
    fi
    
    log_info "Build completed successfully!"
}

run_container() {
    log_info "Starting June Dark OSINT Framework..."
    
    # Stop existing container if running
    if docker ps -q -f name=${CONTAINER_NAME} | grep -q .; then
        log_warn "Stopping existing container..."
        docker stop ${CONTAINER_NAME}
        docker rm ${CONTAINER_NAME}
    fi
    
    # Prepare Docker run command
    DOCKER_CMD="docker run -d --name ${CONTAINER_NAME}"
    
    # Add GPU support if available
    if [ "$GPU_SUPPORT" = true ]; then
        DOCKER_CMD="$DOCKER_CMD --gpus all"
        log_info "GPU acceleration enabled"
    fi
    
    # Add environment variables from .env file
    DOCKER_CMD="$DOCKER_CMD --env-file .env"
    
    # Add port mapping
    DOCKER_CMD="$DOCKER_CMD -p ${PORT}:9009"
    
    # Add restart policy
    DOCKER_CMD="$DOCKER_CMD --restart unless-stopped"
    
    # Add image
    DOCKER_CMD="$DOCKER_CMD ${IMAGE_NAME}:${TAG}"
    
    # Run the container
    eval $DOCKER_CMD
    
    log_info "Container started successfully!"
    log_blue "Access the API at: http://localhost:${PORT}"
    log_blue "API Documentation: http://localhost:${PORT}/docs"
    log_blue "Health Check: http://localhost:${PORT}/health"
    
    # Wait a moment and check status
    sleep 3
    check_status
}

stop_container() {
    log_info "Stopping June Dark OSINT Framework..."
    
    if docker ps -q -f name=${CONTAINER_NAME} | grep -q .; then
        docker stop ${CONTAINER_NAME}
        docker rm ${CONTAINER_NAME}
        log_info "Container stopped and removed."
    else
        log_warn "Container is not running."
    fi
}

show_logs() {
    log_info "Showing logs for June Dark OSINT Framework..."
    
    if docker ps -q -f name=${CONTAINER_NAME} | grep -q .; then
        docker logs -f ${CONTAINER_NAME}
    else
        log_error "Container is not running."
        exit 1
    fi
}

check_status() {
    log_info "Checking June Dark OSINT Framework status..."
    
    if docker ps -q -f name=${CONTAINER_NAME} | grep -q .; then
        log_info "Container is running."
        
        # Check health endpoint
        sleep 2
        if curl -s -f http://localhost:${PORT}/health > /dev/null 2>&1; then
            log_info "✅ Health check passed - API is responding"
            
            # Show detailed status
            echo -e "\n${BLUE}Service Status:${NC}"
            curl -s http://localhost:${PORT}/health | python3 -m json.tool 2>/dev/null || echo "Health endpoint responded but JSON parsing failed"
        else
            log_warn "⚠️  Container is running but health check failed"
            log_info "Check logs with: $0 logs"
        fi
        
        # Show resource usage
        echo -e "\n${BLUE}Resource Usage:${NC}"
        docker stats ${CONTAINER_NAME} --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"
        
    else
        log_error "Container is not running."
        exit 1
    fi
}

show_help() {
    echo "June Dark OSINT Framework Deployment Script"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  build     Build the Docker image"
    echo "  run       Run the container"
    echo "  stop      Stop and remove the container"
    echo "  logs      Show container logs (follow mode)"
    echo "  status    Show container and service status"
    echo "  restart   Restart the container"
    echo "  help      Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 build                 # Build the image"
    echo "  $0 run                   # Start the service"
    echo "  $0 status                # Check if everything is working"
    echo "  $0 logs                  # View real-time logs"
    echo ""
    echo "Configuration:"
    echo "  Edit .env file to configure OpenCTI, Redis, and other settings"
    echo "  Default API port: ${PORT}"
    echo "  Default API docs: http://localhost:${PORT}/docs"
}

# Main script logic
case "${1:-help}" in
    build)
        check_requirements
        build_image
        ;;
    run)
        check_requirements
        run_container
        ;;
    stop)
        stop_container
        ;;
    logs)
        show_logs
        ;;
    status)
        check_status
        ;;
    restart)
        stop_container
        sleep 2
        check_requirements
        run_container
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac