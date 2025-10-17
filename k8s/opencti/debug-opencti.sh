#!/bin/bash
# Debug OpenCTI configuration and connectivity

set -e

echo "🔍 Debugging OpenCTI deployment..."

# Get the actual pod name
SERVER_POD=$(kubectl -n opencti get pods -l app.kubernetes.io/name=opencti,app.kubernetes.io/component=server -o jsonpath='{.items[0].metadata.name}')
echo "Server pod: $SERVER_POD"

if [ -z "$SERVER_POD" ]; then
    echo "No server pod found, checking all pods:"
    kubectl -n opencti get pods
    
    # Try to find any opencti server pod
    SERVER_POD=$(kubectl -n opencti get pods | grep opencti-server | head -1 | awk '{print $1}')
    echo "Found server pod: $SERVER_POD"
fi

if [ -n "$SERVER_POD" ]; then
    echo "📋 1. Checking environment variables in OpenCTI server pod $SERVER_POD:"
    kubectl -n opencti exec "$SERVER_POD" -- printenv | grep -E '^ELASTICSEARCH__|^APP__|^MINIO__|^RABBITMQ__|^REDIS__' | sort
    
    echo "
🌐 2. Testing OpenSearch connectivity from OpenCTI server:"
    kubectl -n opencti exec "$SERVER_POD" -- sh -c '
        echo "Testing DNS resolution:"
        nslookup opensearch-cluster-master.default.svc.cluster.local || echo "DNS failed"
        
        echo "Testing HTTP connection:"
        wget -qO- --timeout=5 http://opensearch-cluster-master.default.svc.cluster.local:9200 || echo "HTTP connection failed"
    '
else
    echo "❌ No OpenCTI server pod found!"
fi

echo "
📊 3. Checking actual Helm values applied:"
helm -n opencti get values opencti

echo "
🔧 4. Checking rendered environment in deployment:"
kubectl -n opencti get deploy opencti-server -o jsonpath='{.spec.template.spec.containers[0].env}' 2>/dev/null | python3 -m json.tool 2>/dev/null || {
    echo "Fallback - raw environment variables:"
    kubectl -n opencti get deploy opencti-server -o jsonpath='{.spec.template.spec.containers[0].env}'
}

echo "
📝 5. Recent server logs:"
if [ -n "$SERVER_POD" ]; then
    kubectl -n opencti logs "$SERVER_POD" --tail=10
else
    kubectl -n opencti logs -l app.kubernetes.io/component=server --tail=10
fi

echo "
✅ Debug complete"