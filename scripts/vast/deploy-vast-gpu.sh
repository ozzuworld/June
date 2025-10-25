#!/bin/bash

# Direct Vast.ai GPU deployment script for June services
# This bypasses SkyPilot and uses Vast.ai CLI directly with USA region filtering

set -e

echo "🔍 Searching for USA GPU instances..."

# Search for RTX 3090/4080/4070S in USA with your preferred specs
SEARCH_QUERY="reliability>99.5 verified=true geolocation=US num_gpus=1 gpu_name=RTX_3090,RTX_4080,RTX_4070S cpu_cores>=8 ram_size>=16 disk_space>=50 direct_port_count>=1"

echo "Query: $SEARCH_QUERY"

# Get available offers (shows top 5 cheapest matching instances)
OFFERS=$(vastai search offers "$SEARCH_QUERY" --raw | head -5)

if [ -z "$OFFERS" ]; then
    echo "❌ No suitable GPU instances found in USA"
    echo "💡 Trying with relaxed geolocation (include Canada)..."
    SEARCH_QUERY="reliability>99.0 verified=true geolocation=US,CA num_gpus=1 gpu_name=RTX_3090,RTX_4080,RTX_4070S cpu_cores>=8 ram_size>=16 disk_space>=50"
    OFFERS=$(vastai search offers "$SEARCH_QUERY" --raw | head -5)
fi

if [ -z "$OFFERS" ]; then
    echo "❌ No suitable instances found. Exiting."
    exit 1
fi

echo "✅ Found available instances:"
vastai search offers "$SEARCH_QUERY" | head -5

# Get the cheapest offer ID
OFFER_ID=$(echo "$OFFERS" | jq -r '.[0].id' 2>/dev/null || echo "$OFFERS" | head -1 | awk '{print $1}')

if [ -z "$OFFER_ID" ]; then
    echo "❌ Could not parse offer ID"
    exit 1
fi

echo "🎯 Selected offer ID: $OFFER_ID"

# Create the onstart script for your June services
cat > /tmp/june_onstart.sh << 'EOF'
#!/bin/bash
set -e
echo "📦 Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh

echo "🔗 Connecting to Headscale VPN..."
tailscale up --authkey=${HEADSCALE_AUTH_KEY} \
  --login-server=https://headscale.ozzu.world \
  --hostname=vast-gpu-$(hostname)

echo "📦 Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
  curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
fi

echo "🖥️ Checking GPU..."
nvidia-smi

echo "🚀 Creating docker-compose.yaml..."
cat > /root/docker-compose.yaml << 'DOCKEREOF'
version: '3.8'
services:
  june-tts:
    image: ozzuworld/june-tts:latest
    container_name: june-tts
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - TTS_PORT=8000
      - TTS_HOME=/app/models
      - TTS_CACHE_PATH=/app/cache
      - ORCHESTRATOR_URL=${ORCHESTRATOR_URL}
    ports:
      - "8000:8000"
    volumes:
      - tts-models:/app/models
      - tts-cache:/app/cache
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3

  june-stt:
    image: ozzuworld/june-stt:latest
    container_name: june-stt
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - STT_PORT=8001
      - WHISPER_DEVICE=cuda
      - WHISPER_COMPUTE_TYPE=float16
      - ORCHESTRATOR_URL=${ORCHESTRATOR_URL}
      - LIVEKIT_URL=${LIVEKIT_URL}
      - ROOM_NAME=ozzu-main
    ports:
      - "8001:8001"
    volumes:
      - stt-models:/app/models
      - stt-cache:/app/cache
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  tts-models:
  tts-cache:
  stt-models:
  stt-cache:
DOCKEREOF

cd /root
echo "🚀 Starting GPU services..."
docker-compose up -d

echo "⏳ Waiting for services to be healthy..."
for i in {1..30}; do
  if curl -sf http://localhost:8000/healthz && curl -sf http://localhost:8001/healthz; then
    echo "✅ All services healthy"
    break
  fi
  echo "Waiting... ($i/30)"
  sleep 10
done

echo "📊 Tailscale Status:"
tailscale status

echo "🎉 June GPU services are running!"
docker-compose logs -f
EOF

echo "📋 Creating instance with offer ID: $OFFER_ID"

# Create the instance
vastai create instance "$OFFER_ID" \
  --image ubuntu:22.04 \
  --disk 50 \
  --ssh \
  --direct \
  --onstart /tmp/june_onstart.sh \
  --env "-p 22:22 -p 8000:8000 -p 8001:8001 -e HEADSCALE_AUTH_KEY=${HEADSCALE_AUTH_KEY} -e ORCHESTRATOR_URL=${ORCHESTRATOR_URL} -e LIVEKIT_URL=${LIVEKIT_URL}"

echo "✅ Instance creation requested!"
echo "🔍 Check status with: vastai show instances"
echo "📡 Connect via SSH when ready using the provided IP from 'vastai show instances'"
