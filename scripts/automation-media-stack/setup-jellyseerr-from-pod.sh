#!/bin/bash
# Run Jellyseerr setup automation from inside the Jellyseerr pod
# This allows it to use internal Kubernetes DNS names

set -e

DOMAIN="$1"
JELLYFIN_USER="$2"
JELLYFIN_PASS="$3"

if [ -z "$DOMAIN" ] || [ -z "$JELLYFIN_USER" ] || [ -z "$JELLYFIN_PASS" ]; then
    echo "Usage: $0 <domain> <jellyfin-user> <jellyfin-pass>"
    exit 1
fi

# Copy the Python script into the Jellyseerr pod
echo "[INFO] Copying setup script to Jellyseerr pod..."
POD_NAME=$(kubectl get pod -n june-services -l app=jellyseerr -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD_NAME" ]; then
    echo "[ERROR] Jellyseerr pod not found"
    exit 1
fi

echo "[INFO] Found Jellyseerr pod: $POD_NAME"

# Copy the script
kubectl cp "$(dirname "$0")/setup-jellyseerr-wizard.py" \
    "june-services/$POD_NAME:/tmp/setup-jellyseerr.py"

# Copy API key files into the pod
echo "[INFO] Copying API keys to pod..."
kubectl cp /root/.radarr-api-key "june-services/$POD_NAME:/tmp/radarr-api-key" 2>/dev/null || echo "[WARN] Radarr API key not found"
kubectl cp /root/.sonarr-api-key "june-services/$POD_NAME:/tmp/sonarr-api-key" 2>/dev/null || echo "[WARN] Sonarr API key not found"

# Install Python requests library if not present
echo "[INFO] Ensuring Python dependencies are installed..."
kubectl exec -n june-services "$POD_NAME" -- sh -c "pip install requests 2>/dev/null || apk add py3-requests 2>/dev/null || apt-get update && apt-get install -y python3-requests 2>/dev/null || true"

# Run the setup script from inside the pod
echo "[INFO] Running Jellyseerr setup from inside pod..."
kubectl exec -n june-services "$POD_NAME" -- python3 /tmp/setup-jellyseerr.py \
    --url "http://localhost:5055" \
    --domain "$DOMAIN" \
    --jellyfin-user "$JELLYFIN_USER" \
    --jellyfin-pass "$JELLYFIN_PASS" \
    --jellyfin-url "http://jellyfin.june-services.svc.cluster.local:8096"

echo "[SUCCESS] Jellyseerr setup completed from pod"
