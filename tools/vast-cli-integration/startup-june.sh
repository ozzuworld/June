#!/bin/bash
#
# June Services Startup Script for Vast.ai
# This script sets up and runs the June TTS/STT services with Tailscale networking
#

set -euo pipefail

# Configuration with defaults
TTS_PORT=${TTS_PORT:-8000}
STT_PORT=${STT_PORT:-8001}
TAILSCALE_AUTH_KEY=${TAILSCALE_AUTH_KEY:-}
TAILSCALE_HOSTNAME=${TAILSCALE_HOSTNAME:-june-gpu-$(hostname)}
COMPOSE_URL=${COMPOSE_URL:-https://raw.githubusercontent.com/ozzuworld/June/feature/clean-vast-cli/tools/vast-cli-integration/june-stack.yml}

echo "[SETUP] Starting June services setup on Vast.ai instance..."
echo "[SETUP] Hostname: $(hostname)"
echo "[SETUP] TTS Port: $TTS_PORT"
echo "[SETUP] STT Port: $STT_PORT"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Update system packages
log "Updating system packages..."
apt-get update -qq

# Install required packages
log "Installing required packages..."
apt-get install -y -qq curl wget jq

# Install Docker Compose if not present
if ! command_exists docker; then
    log "Docker not found! This script requires Docker to be pre-installed."
    exit 1
fi

# Install Docker Compose
if ! docker compose version >/dev/null 2>&1; then
    if ! command_exists docker-compose; then
        log "Installing Docker Compose..."
        COMPOSE_VERSION="2.27.0"
        curl -L "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" \
            -o /usr/local/bin/docker-compose
        chmod +x /usr/local/bin/docker-compose
        ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose
        log "Docker Compose installed successfully"
    fi
fi

# Create working directory
WORK_DIR="/opt/june"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Download Docker Compose file
log "Downloading June stack configuration..."
if ! curl -sf "$COMPOSE_URL" -o june-stack.yml; then
    log "Failed to download compose file from $COMPOSE_URL"
    log "Using embedded configuration..."
    
    # Fallback to embedded compose file
    cat > june-stack.yml <<'EOF'
version: "3.9"

services:
  june-tts:
    image: ghcr.io/ozzuworld/june-tts:latest
    container_name: june-tts
    restart: unless-stopped
    environment:
      - TTS_PORT=${TTS_PORT:-8000}
      - TTS_HOME=/app/models
      - NUMBA_DISABLE_JIT=1
      - NUMBA_CACHE_DIR=/tmp/numba_cache
      - PYTORCH_JIT=0
      - OMP_NUM_THREADS=1
    volumes:
      - tts-models:/app/models
      - tts-cache:/app/cache
    ports:
      - "${TTS_PORT:-8000}:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  june-stt:
    image: ghcr.io/ozzuworld/june-stt:latest
    container_name: june-stt
    restart: unless-stopped
    environment:
      - STT_PORT=${STT_PORT:-8001}
      - WHISPER_DEVICE=cuda
      - WHISPER_COMPUTE_TYPE=float16
      - NUMBA_DISABLE_JIT=1
      - NUMBA_CACHE_DIR=/tmp/numba_cache
    volumes:
      - stt-models:/app/models
      - stt-cache:/app/cache
    ports:
      - "${STT_PORT:-8001}:8001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

volumes:
  tts-models: {}
  tts-cache: {}
  stt-models: {}
  stt-cache: {}
EOF
fi

# Create environment file
log "Creating environment configuration..."
cat > .env <<EOF
TTS_PORT=$TTS_PORT
STT_PORT=$STT_PORT
TAILSCALE_AUTH_KEY=$TAILSCALE_AUTH_KEY
TAILSCALE_HOSTNAME=$TAILSCALE_HOSTNAME
COMPOSE_PROJECT_NAME=june
EOF

# Set up Tailscale if auth key is provided
if [ -n "$TAILSCALE_AUTH_KEY" ]; then
    log "Setting up Tailscale networking..."
    
    # Install Tailscale
    if ! command_exists tailscale; then
        log "Installing Tailscale..."
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
    
    # Start Tailscale
    log "Connecting to Tailscale network..."
    tailscale up --authkey="$TAILSCALE_AUTH_KEY" --hostname="$TAILSCALE_HOSTNAME" --accept-routes
    
    # Get Tailscale IP
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "pending")
    log "Tailscale IP: $TAILSCALE_IP"
else
    log "No Tailscale auth key provided, skipping Tailscale setup"
fi

# Pull Docker images
log "Pulling Docker images..."
docker compose --env-file .env -f june-stack.yml pull

# Start services
log "Starting June services..."
if docker compose version >/dev/null 2>&1; then
    docker compose --env-file .env -f june-stack.yml up -d
else
    docker-compose --env-file .env -f june-stack.yml up -d
fi

# Wait for services to be healthy
log "Waiting for services to start..."
max_attempts=60
attempt=0

while [ $attempt -lt $max_attempts ]; do
    attempt=$((attempt + 1))
    
    # Check TTS service
    if curl -sf "http://localhost:${TTS_PORT}/healthz" >/dev/null 2>&1; then
        tts_healthy=true
    else
        tts_healthy=false
    fi
    
    # Check STT service  
    if curl -sf "http://localhost:${STT_PORT}/healthz" >/dev/null 2>&1; then
        stt_healthy=true
    else
        stt_healthy=false
    fi
    
    if [ "$tts_healthy" = true ] && [ "$stt_healthy" = true ]; then
        log "✓ All services are healthy!"
        break
    fi
    
    log "Services starting... (${attempt}/${max_attempts})"
    sleep 5
done

if [ $attempt -eq $max_attempts ]; then
    log "WARNING: Services did not become healthy within expected time"
    log "Checking service status..."
    docker compose --env-file .env -f june-stack.yml ps
    docker compose --env-file .env -f june-stack.yml logs --tail=20
else
    log "✓ June services successfully started!"
    
    # Show service information
    echo
    log "=== Service Information ==="
    log "TTS Service: http://localhost:${TTS_PORT}"
    log "STT Service: http://localhost:${STT_PORT}"
    
    if [ -n "$TAILSCALE_AUTH_KEY" ] && [ "$TAILSCALE_IP" != "pending" ]; then
        log "TTS via Tailscale: http://${TAILSCALE_IP}:${TTS_PORT}"
        log "STT via Tailscale: http://${TAILSCALE_IP}:${STT_PORT}"
    fi
    
    log "Docker containers:"
    docker compose --env-file .env -f june-stack.yml ps --format "table"
fi

log "Setup complete!"