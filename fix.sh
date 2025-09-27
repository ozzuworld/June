#!/bin/bash
# Fix TTS Connection - Exact Commands for IP 47.19.39.146:5975

echo "🔧 Fixing TTS Connection to 47.19.39.146:5975"
echo "=============================================="

# Step 1: Test TTS service accessibility first
echo "📋 Step 1: Testing TTS Service Accessibility"
echo "--------------------------------------------"
echo "Testing if TTS service is reachable..."
curl -v --max-time 10 http://47.19.39.146:5975/healthz || echo "❌ TTS service not reachable"
curl -v --max-time 10 http://47.19.39.146:5975/ || echo "❌ TTS root endpoint not reachable"

echo ""
echo "📋 Step 2: Update Orchestrator Configuration"
echo "-------------------------------------------"
echo "Updating orchestrator deployment with correct TTS URL..."

# Update the orchestrator deployment with the correct TTS URL
kubectl patch deployment june-orchestrator -n june-services -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "orchestrator",
          "env": [
            {
              "name": "TTS_SERVICE_URL",
              "value": "http://47.19.39.146:5975"
            },
            {
              "name": "TTS_DEFAULT_VOICE",
              "value": "default"
            },
            {
              "name": "TTS_DEFAULT_SPEED", 
              "value": "1.0"
            },
            {
              "name": "TTS_DEFAULT_LANGUAGE",
              "value": "EN"
            }
          ]
        }]
      }
    }
  }
}'

echo "✅ Deployment patched"

echo ""
echo "📋 Step 3: Restart Orchestrator"
echo "------------------------------"
echo "Restarting orchestrator to pick up new configuration..."
kubectl rollout restart deployment/june-orchestrator -n june-services

echo "✅ Orchestrator restart initiated"

echo ""
echo "📋 Step 4: Wait for Rollout"
echo "-------------------------"
echo "Waiting for rollout to complete..."
kubectl rollout status deployment/june-orchestrator -n june-services --timeout=120s

echo ""
echo "📋 Step 5: Verify Configuration"
echo "------------------------------"
echo "Checking if environment variables are set correctly..."
sleep 10  # Wait for pod to be ready

ORCH_POD=$(kubectl get pods -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}')
echo "Orchestrator pod: $ORCH_POD"

if [ ! -z "$ORCH_POD" ]; then
    echo ""
    echo "Environment variables in orchestrator:"
    kubectl exec -n june-services $ORCH_POD -- env | grep TTS || echo "No TTS environment variables found"
    
    echo ""
    echo "📋 Step 6: Test TTS Connection from Orchestrator Pod"
    echo "--------------------------------------------------"
    echo "Testing TTS connection from inside orchestrator pod..."
    
    # Test basic connectivity
    kubectl exec -n june-services $ORCH_POD -- curl -v --max-time 10 http://47.19.39.146:5975/healthz || echo "❌ TTS health check failed"
    
    echo ""
    echo "Testing TTS synthesis endpoint..."
    kubectl exec -n june-services $ORCH_POD -- curl -X POST \
        -H "Content-Type: application/json" \
        -d '{"text":"test","voice":"default","speed":1.0,"language":"EN","format":"wav"}' \
        --max-time 15 \
        http://47.19.39.146:5975/v1/tts \
        -o /dev/null -w "HTTP Status: %{http_code}, Total Time: %{time_total}s\n" || echo "❌ TTS synthesis test failed"
else
    echo "❌ Could not find orchestrator pod"
fi

echo ""
echo "📋 Step 7: Check Orchestrator Logs"
echo "---------------------------------"
echo "Recent orchestrator logs (last 20 lines):"
kubectl logs -n june-services -l app=june-orchestrator --tail=20

echo ""
echo "📋 Step 8: Test TTS via Orchestrator API"
echo "---------------------------------------"
echo "Testing the full flow via orchestrator API..."
echo "You can test this manually with:"
echo ""
echo "curl -X POST http://YOUR_ORCHESTRATOR_URL/v1/chat \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"text\":\"Hello world\",\"include_audio\":true}'"

echo ""
echo "🎯 Configuration Summary"
echo "======================"
echo "TTS Service URL: http://47.19.39.146:5975"
echo "Orchestrator should now be configured to use this URL"
echo ""
echo "If you still see connection errors:"
echo "1. Verify TTS service is running on 47.19.39.146:5975"
echo "2. Check firewall rules allow traffic on port 5975"
echo "3. Ensure TTS service accepts external connections (not just localhost