#!/bin/bash
# fix-ingress-services.sh - Fix services for GKE ingress

set -euo pipefail

echo "🔧 Fixing services for GKE ingress..."

# Add NEG annotations to services
kubectl annotate service june-orchestrator -n june-services \
  cloud.google.com/neg='{"ingress": true}' --overwrite

kubectl annotate service june-stt -n june-services \
  cloud.google.com/neg='{"ingress": true}' --overwrite

kubectl annotate service june-idp -n june-services \
  cloud.google.com/neg='{"ingress": true}' --overwrite

# If media relay exists
kubectl annotate service june-media-relay -n june-services \
  cloud.google.com/neg='{"ingress": true}' --overwrite 2>/dev/null || echo "Media relay service not found (OK if Phase 1 not deployed)"

echo "✅ Services updated with NEG annotations"

# Check service status
echo ""
echo "📊 Service status:"
kubectl get services -n june-services

echo ""
echo "🔍 Service annotations:"
kubectl get services -n june-services -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.annotations.cloud\.google\.com/neg}{"\n"}{end}'