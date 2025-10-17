#!/usr/bin/env bash
# OpenSearch Recovery Script for OpenCTI
# Clears indices and ISM policies when initialization fails
set -euo pipefail

NS="${1:-opencti}"
SVC="opensearch-cluster-master"
PORT="${PORT:-9200}"
TIMEOUT="${TIMEOUT:-30}"

echo "🔄 Resetting OpenSearch for OpenCTI in namespace: $NS"
echo "   Service: $SVC"
echo "   Port: $PORT"
echo

# Check if OpenSearch service exists
if ! kubectl get svc "$SVC" -n "$NS" >/dev/null 2>&1; then
  echo "❌ Error: OpenSearch service $SVC not found in namespace $NS"
  exit 1
fi

# Port forward to OpenSearch
echo "📡 Setting up port forward to OpenSearch..."
kubectl port-forward -n "$NS" svc/"$SVC" "$PORT":9200 >/tmp/opensearch-pf.log 2>&1 &
PF_PID=$!

# Wait for port forward to be ready
sleep 3

# Function to cleanup port forward
cleanup() {
  if [[ -n "${PF_PID:-}" ]]; then
    echo "🔌 Stopping port forward (PID: $PF_PID)..."
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Test connection
echo "🔍 Testing OpenSearch connection..."
if ! curl -s --max-time 5 "http://localhost:$PORT/_cluster/health" >/dev/null; then
  echo "❌ Error: Cannot connect to OpenSearch at localhost:$PORT"
  echo "   Check if OpenSearch pod is running: kubectl get pods -n $NS -l app=opensearch"
  exit 1
fi

echo "✅ Connected to OpenSearch"
echo

# Delete OpenCTI indices
echo "🗑️  Deleting OpenCTI indices..."
DELETE_INDICES=$(curl -s -X DELETE "http://localhost:$PORT/opencti*" 2>/dev/null || echo "No indices found")
echo "   Result: $DELETE_INDICES"

# Delete OpenCTI ISM policies
echo "🗑️  Deleting OpenCTI ISM policies..."
DELETE_POLICY1=$(curl -s -X DELETE "http://localhost:$PORT/_plugins/_ism/policies/opencti-ism-policy" 2>/dev/null || echo "Policy not found")
echo "   opencti-ism-policy: $DELETE_POLICY1"

DELETE_POLICY2=$(curl -s -X DELETE "http://localhost:$PORT/_plugins/_ism/policies/opencti*" 2>/dev/null || echo "No policies found")
echo "   opencti* policies: $DELETE_POLICY2"

# Verify cleanup
echo
echo "🔍 Verifying cleanup..."
INDICES=$(curl -s "http://localhost:$PORT/_cat/indices/opencti*" 2>/dev/null || echo "No OpenCTI indices found")
if [[ "$INDICES" == *"opencti"* ]]; then
  echo "⚠️  Warning: Some OpenCTI indices still exist:"
  echo "$INDICES"
else
  echo "✅ All OpenCTI indices removed"
fi

POLICIES=$(curl -s "http://localhost:$PORT/_plugins/_ism/policies" 2>/dev/null | grep -i opencti || echo "")
if [[ -n "$POLICIES" ]]; then
  echo "⚠️  Warning: Some OpenCTI policies still exist:"
  echo "$POLICIES"
else
  echo "✅ All OpenCTI ISM policies removed"
fi

echo
echo "🎯 OpenSearch reset complete!"
echo "   Next steps:"
echo "   1. Restart OpenCTI server: kubectl delete pods -l opencti.component=server -n $NS"
echo "   2. Monitor logs: kubectl logs -f deployment/opencti-server -n $NS"
echo "   3. If issues persist, restart OpenSearch: kubectl delete pod -l app=opensearch-cluster-master -n $NS"
echo