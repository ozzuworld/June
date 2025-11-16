#!/bin/bash
# Script to get current qBittorrent temporary password from logs

POD_NAME=$(kubectl get pod -n june-services -l app=qbittorrent -o jsonpath='{.items[0].metadata.name}')

echo "🔍 qBittorrent Temporary Password"
echo "=================================="
echo ""
kubectl logs -n june-services "$POD_NAME" | grep -A 1 "temporary password"
echo ""
echo "📝 Use this password to login at: https://qbittorrent.ozzu.world"
echo "   Then change it to: Pokemon123!"
echo ""
