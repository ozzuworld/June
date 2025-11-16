#!/bin/bash
# Check if Jellyseerr is already initialized

POD_NAME=$(kubectl get pod -n june-services -l app=jellyseerr -o jsonpath='{.items[0].metadata.name}')

echo "Checking Jellyseerr initialization status..."
echo ""

# Check settings/public endpoint
echo "Checking /api/v1/settings/public..."
kubectl exec -n june-services "$POD_NAME" -- wget -q -O- http://localhost:5055/api/v1/settings/public 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "Failed to get settings"

echo ""
echo "Checking if config file exists..."
kubectl exec -n june-services "$POD_NAME" -- ls -la /app/config/ 2>/dev/null || echo "No config directory"

echo ""
echo "Looking for settings.json..."
kubectl exec -n june-services "$POD_NAME" -- cat /app/config/settings.json 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "No settings.json found"
