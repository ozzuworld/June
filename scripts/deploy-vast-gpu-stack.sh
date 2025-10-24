#!/bin/bash
# Deploy split STT/TTS stack on Vast.ai with prebuilt images
# Usage: ./scripts/deploy-vast-gpu-stack.sh

set -euo pipefail

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info(){ echo -e "${BLUE}[INFO]${NC} $*"; }
success(){ echo -e "${GREEN}[SUCCESS]${NC} $*"; }
warn(){ echo -e "${YELLOW}[WARN]${NC} $*"; }
err(){ echo -e "${RED}[ERROR]${NC} $*"; }

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &> /dev/null && pwd)
STACK_FILE="$ROOT_DIR/deployments/vast/june-gpu-stack.compose.yml"

if [ ! -f "$STACK_FILE" ]; then
  err "Compose file not found: $STACK_FILE"; exit 1
fi

# Prepare .env
if [ ! -f .env ]; then
  info "Creating .env file..."
  cat > .env << EOF
# Required for container-level Tailscale (Headscale auth)
TAILSCALE_AUTH_KEY=

# Optional service ports override
TTS_PORT=8000
STT_PORT=8001
EOF
  warn "Edit .env and set TAILSCALE_AUTH_KEY before first run."
fi

source .env

if [ -z "${TAILSCALE_AUTH_KEY:-}" ]; then
  warn "TAILSCALE_AUTH_KEY not set. You can still start, but Tailscale won't connect."
fi

info "Bringing up june-tts and june-stt using prebuilt images..."
docker compose -f "$STACK_FILE" --env-file .env up -d

sleep 5

info "Checking container status..."
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E 'june-(tts|stt)' || true

info "Health checks:"
if curl -sf http://localhost:${TTS_PORT:-8000}/healthz > /dev/null; then success "TTS healthy"; else warn "TTS not ready"; fi
if curl -sf http://localhost:${STT_PORT:-8001}/healthz > /dev/null; then success "STT healthy"; else warn "STT not ready"; fi

info "Tailscale status inside containers (if key provided):"
for c in june-tts june-stt; do
  if docker exec "$c" tailscale status >/dev/null 2>&1; then
    success "$c connected to Headscale"; docker exec "$c" tailscale status | head -5
  else
    warn "$c tailscale not connected yet or tailscale not available"
  fi
done

success "Deployment completed."
info "Logs: docker logs -f june-tts | docker logs -f june-stt"
