#!/bin/bash
# Debug OpenCTI configuration and connectivity

set -e

echo "🔍 Debugging OpenCTI deployment..."

echo "📋 1. Checking environment variables in OpenCTI server:"
kubectl -n opencti exec deploy/opencti-server -- printenv | grep -E '^ELASTICSEARCH__|^APP__|^MINIO__|^RABBITMQ__|^REDIS__' | sort

echo "
🌐 2. Testing OpenSearch connectivity from OpenCTI server:"
kubectl -n opencti exec deploy/opencti-server -- sh -c '
    echo "Testing DNS resolution:"
    nslookup opensearch-cluster-master.default.svc.cluster.local || echo "DNS failed"
    
    echo "Testing HTTP connection:"
    wget -qO- --timeout=5 http://opensearch-cluster-master.default.svc.cluster.local:9200 || echo "HTTP connection failed"
    
    echo "Testing with curl (if available):"
    curl -s --connect-timeout 5 http://opensearch-cluster-master.default.svc.cluster.local:9200 || echo "curl failed or not available"
'

echo "
📊 3. Checking actual Helm values applied:"
helm -n opencti get values opencti

echo "
🔧 4. Checking rendered environment in deployment:"
kubectl -n opencti get deploy opencti-server -o jsonpath='{.spec.template.spec.containers[0].env}' | jq '.' || echo "jq not available, raw output:"
kubectl -n opencti get deploy opencti-server -o jsonpath='{.spec.template.spec.containers[0].env}'

echo "
📝 5. Recent server logs:"
kubectl -n opencti logs deploy/opencti-server --tail=20

echo "
✅ Debug complete"