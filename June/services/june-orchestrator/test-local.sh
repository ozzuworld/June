#!/bin/bash
# Test the orchestrator locally before deployment

echo "🧪 Testing June Orchestrator locally..."

# Build image
docker build -t june-orchestrator-test .

# Run container
docker run -d --name june-test -p 8080:8080 \
  -e GEMINI_API_KEY="${GEMINI_API_KEY:-}" \
  june-orchestrator-test

# Wait for startup
sleep 5

# Test endpoints
echo "Testing health endpoint..."
curl -s http://localhost:8080/healthz | jq '.' || curl -s http://localhost:8080/healthz

echo -e "\nTesting chat endpoint..."
curl -s -X POST http://localhost:8080/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello test"}' | jq '.' || \
  curl -s -X POST http://localhost:8080/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello test"}'

echo -e "\nTesting version endpoint..."
curl -s http://localhost:8080/v1/version | jq '.' || curl -s http://localhost:8080/v1/version

# Cleanup
docker stop june-test && docker rm june-test
docker rmi june-orchestrator-test

echo "✅ Local test complete!"
