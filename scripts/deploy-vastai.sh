#!/bin/bash
# vast.ai deployment script for June STT/TTS services
# Usage: ./deploy-vastai.sh

set -euo pipefail

# Configuration
DOCKER_REGISTRY="your-registry.com"
TAILSCALE_KEY="${TAILSCALE_AUTH_KEY}"
WORKSPACE_DIR="/workspace"

echo "🚀 Starting June STT/TTS deployment on vast.ai..."

# 1. System Setup
setup_system() {
    echo "📦 Installing system dependencies..."
    
    # Update system
    sudo apt-get update -qq
    
    # Install Docker Compose if not available
    if ! command -v docker-compose &> /dev/null; then
        sudo curl -L "https://github.com/docker/compose/releases/download/v2.21.0/docker-compose-linux-x86_64" \
            -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
    fi
    
    # Install monitoring tools
    sudo apt-get install -y htop iftop nvidia-ml-py3
    pip install gpustat
    
    echo "✅ System setup complete"
}

# 2. Tailscale Setup  
setup_tailscale() {
    echo "🔗 Setting up Tailscale networking..."
    
    if ! command -v tailscale &> /dev/null; then
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
    
    # Connect to your tailnet
    if [ -n "${TAILSCALE_KEY}" ]; then
        sudo tailscale up --authkey="${TAILSCALE_KEY}" --accept-routes
        echo "✅ Tailscale connected: $(tailscale ip -4)"
    else
        echo "⚠️  TAILSCALE_AUTH_KEY not set - manual setup required"
        echo "Run: sudo tailscale up"
    fi
}

# 3. Workspace Preparation
setup_workspace() {
    echo "📁 Preparing workspace directories..."
    
    mkdir -p "${WORKSPACE_DIR}"/{models,cache,logs,data}
    
    # Set permissions for Docker containers
    sudo chown -R 1001:1001 "${WORKSPACE_DIR}"/{models,cache}
    
    # Create symlinks for easy access
    ln -sf "${WORKSPACE_DIR}/logs" ~/logs
    ln -sf "${WORKSPACE_DIR}/models" ~/models
    
    echo "✅ Workspace ready at ${WORKSPACE_DIR}"
}

# 4. Docker Registry Authentication
setup_registry() {
    echo "🔑 Configuring Docker registry access..."
    
    if [ -n "${DOCKER_REGISTRY_TOKEN:-}" ]; then
        echo "${DOCKER_REGISTRY_TOKEN}" | docker login "${DOCKER_REGISTRY}" --username "${DOCKER_REGISTRY_USER}" --password-stdin
        echo "✅ Registry authentication successful"
    else
        echo "⚠️  Registry credentials not provided - using public images only"
    fi
}

# 5. Service Deployment
deploy_services() {
    echo "🐳 Deploying June STT/TTS services..."
    
    # Pull latest images (if using registry)
    if [ -n "${DOCKER_REGISTRY_TOKEN:-}" ]; then
        docker-compose -f docker-compose.vastai.yml pull
    fi
    
    # Start services
    docker-compose -f docker-compose.vastai.yml up -d
    
    echo "⏳ Waiting for services to start..."
    sleep 30
    
    # Health check
    check_health
}

# 6. Health Monitoring
check_health() {
    echo "🔍 Performing health checks..."
    
    # Check STT service
    if curl -sf http://localhost:8001/healthz > /dev/null; then
        echo "✅ STT service healthy"
    else
        echo "❌ STT service unhealthy"
        docker logs june-stt-vastai --tail 20
    fi
    
    # Check TTS service
    if curl -sf http://localhost:8000/healthz > /dev/null; then
        echo "✅ TTS service healthy"
    else
        echo "❌ TTS service unhealthy"
        docker logs june-tts-vastai --tail 20
    fi
    
    # GPU utilization
    echo "📊 GPU Status:"
    nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits
}

# 7. Monitoring Setup
setup_monitoring() {
    echo "📈 Setting up monitoring..."
    
    # Create monitoring script
    cat > /usr/local/bin/monitor-june << 'EOF'
#!/bin/bash
echo "=== June Services Status ==="
echo "Services:"
docker-compose -f /workspace/docker-compose.vastai.yml ps

echo -e "\n=== GPU Usage ==="
gpustat --no-color

echo -e "\n=== Memory Usage ==="
free -h

echo -e "\n=== Disk Usage ==="
df -h /workspace

echo -e "\n=== Service Logs (Last 5 lines) ==="
echo "STT Service:"
docker logs june-stt-vastai --tail 5 2>/dev/null || echo "Service not running"
echo "TTS Service:"  
docker logs june-tts-vastai --tail 5 2>/dev/null || echo "Service not running"
EOF
    
    chmod +x /usr/local/bin/monitor-june
    
    # Add to bashrc for easy access
    echo 'alias monitor="monitor-june"' >> ~/.bashrc
    
    echo "✅ Run 'monitor' to check system status"
}

# Main execution
main() {
    echo "🎯 June Platform Deployment Starting..."
    echo "Instance: $(hostname)"
    echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"
    echo "Memory: $(free -h | grep Mem | awk '{print $2}')"
    echo ""
    
    setup_system
    setup_tailscale
    setup_workspace
    setup_registry
    deploy_services
    setup_monitoring
    
    echo ""
    echo "🎉 Deployment Complete!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📍 Services:"
    echo "   STT: http://localhost:8001"
    echo "   TTS: http://localhost:8000"
    echo "   Tailscale IP: $(tailscale ip -4 2>/dev/null || echo 'Not connected')"
    echo ""
    echo "🔧 Management:"
    echo "   Logs: docker-compose -f docker-compose.vastai.yml logs -f"
    echo "   Status: monitor"
    echo "   Restart: docker-compose -f docker-compose.vastai.yml restart"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Error handling
trap 'echo "❌ Deployment failed at line $LINENO"' ERR

# Run if called directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi