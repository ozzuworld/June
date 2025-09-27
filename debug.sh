#!/bin/bash
# Debug TTS 500 Error

echo "🔍 Debugging TTS 500 Error"
echo "========================="

# Step 1: Test TTS endpoints to see what's working
echo "📋 Step 1: Testing TTS Service Endpoints"
echo "---------------------------------------"

echo "Testing /healthz..."
curl -s http://47.19.39.146:5975/healthz | jq . || curl -s http://47.19.39.146:5975/healthz

echo ""
echo "Testing /v1/status..."
curl -s http://47.19.39.146:5975/v1/status | jq . || curl -s http://47.19.39.146:5975/v1/status

echo ""
echo "Testing /v1/voices..."
curl -s http://47.19.39.146:5975/v1/voices | jq . || curl -s http://47.19.39.146:5975/v1/voices

echo ""
echo "📋 Step 2: Test Simple TTS Synthesis"
echo "-----------------------------------"
echo "Testing with minimal payload..."
curl -X POST http://47.19.39.146:5975/v1/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"hello"}' \
  -v

echo ""
echo "📋 Step 3: Test Different TTS Endpoints"
echo "--------------------------------------"
echo "Trying alternative endpoints..."

# Try different possible endpoints
ENDPOINTS=(
    "/v1/tts"
    "/tts"
    "/tts/generate"
    "/v1/synthesize"
    "/synthesize"
)

for endpoint in "${ENDPOINTS[@]}"; do
    echo ""
    echo "Testing $endpoint..."
    curl -X POST "http://47.19.39.146:5975$endpoint" \
        -H "Content-Type: application/json" \
        -d '{"text":"test","voice":"default","language":"EN"}' \
        -w "Status: %{http_code}\n" \
        -s -o /dev/null || echo "Failed"
done

echo ""
echo "📋 Step 4: Check What the Orchestrator is Actually Sending"
echo "---------------------------------------------------------"
echo "Let's see the exact request the orchestrator makes..."

# Get orchestrator pod
ORCH_POD=$(kubectl get pods -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}')

echo "Orchestrator pod: $ORCH_POD"

# Test with the exact same request format as orchestrator
echo ""
echo "Testing orchestrator-style request..."
kubectl exec -n june-services $ORCH_POD -- curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello world test","voice":"default","speed":1.0,"language":"EN","format":"wav"}' \
  -w "Status: %{http_code}, Time: %{time_total}s\n" \
  -v \
  http://47.19.39.146:5975/v1/tts

echo ""
echo "📋 Step 5: Alternative Request Formats"
echo "-------------------------------------"
echo "Testing different request formats that might work..."

# Format 1: Simple format
echo "Format 1: Simple request"
curl -X POST http://47.19.39.146:5975/v1/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"test"}' \
  -w "Status: %{http_code}\n" -s -o /dev/null

# Format 2: Standard TTS format
echo "Format 2: Standard TTS format"
curl -X POST http://47.19.39.146:5975/v1/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"test","language":"EN"}' \
  -w "Status: %{http_code}\n" -s -o /dev/null

# Format 3: Different voice parameter
echo "Format 3: With speaker_id instead of voice"
curl -X POST http://47.19.39.146:5975/v1/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"test","speaker_id":0,"language":"EN"}' \
  -w "Status: %{http_code}\n" -s -o /dev/null

echo ""
echo "📋 Step 6: Check TTS Service Documentation"
echo "-----------------------------------------"
echo "Getting API documentation from TTS service..."
curl -s http://47.19.39.146:5975/docs || curl -s http://47.19.39.146:5975/openapi.json || echo "No docs endpoint found"

echo ""
echo "🎯 Recommendations"
echo "=================="
echo "1. The TTS service is running but returning 500 errors for synthesis"
echo "2. Check TTS service logs to see what's causing the 500 error"
echo "3. The request format might not match what the TTS service expects"
echo "4. Try testing with the TTS service directly to find the correct API format"