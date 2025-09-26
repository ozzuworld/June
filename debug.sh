#!/bin/bash
# Check current auto-deployment readiness

echo "🔍 Checking Auto-Deployment Readiness"
echo "====================================="

# Check 1: GitHub Workflow exists
echo -e "\n1. GitHub Workflow:"
if [ -f ".github/workflows/deploy-gke.yml" ]; then
    echo "✅ GitHub workflow exists"
    echo "   Path: .github/workflows/deploy-gke.yml"
else
    echo "❌ No GitHub workflow found"
fi

# Check 2: Orchestrator source location
echo -e "\n2. Orchestrator Source:"
if [ -f "June/services/june-orchestrator/app.py" ]; then
    echo "✅ Orchestrator app.py in correct location"
    if grep -q "/v1/chat" "June/services/june-orchestrator/app.py"; then
        echo "✅ Contains /v1/chat endpoint"
    else
        echo "❌ Missing /v1/chat endpoint"
    fi
else
    echo "❌ No app.py in June/services/june-orchestrator/"
fi

# Check 3: Dockerfile
echo -e "\n3. Dockerfile:"
if [ -f "June/services/june-orchestrator/Dockerfile" ]; then
    echo "✅ Dockerfile exists in service directory"
else
    echo "❌ No Dockerfile in service directory"
fi

# Check 4: Current deployment image
echo -e "\n4. Current Deployment:"
CURRENT_IMAGE=$(kubectl get deployment june-orchestrator -n june-services -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
if [ ! -z "$CURRENT_IMAGE" ]; then
    echo "✅ Current image: $CURRENT_IMAGE"
    
    # Check if using SHA-based or version-based tag
    if [[ "$CURRENT_IMAGE" =~ :[a-f0-9]{40}$ ]]; then
        echo "✅ Using SHA-based tag (auto-deploy ready)"
    elif [[ "$CURRENT_IMAGE" =~ :v[0-9] ]]; then
        echo "⚠️  Using version tag (needs workflow update)"
    else
        echo "❓ Unknown tag format"
    fi
else
    echo "❌ Cannot access deployment"
fi

# Check 5: Service status
echo -e "\n5. Service Status:"
POD_STATUS=$(kubectl get pods -n june-services -l app=june-orchestrator -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
if [ "$POD_STATUS" = "Running" ]; then
    echo "✅ Pod is running"
else
    echo "❌ Pod status: ${POD_STATUS:-unknown}"
fi

# Check 6: External connectivity
echo -e "\n6. External Connectivity:"
HTTP_CODE=$(curl -s -w "%{http_code}" -o /dev/null https://api.allsafe.world/healthz 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ External endpoint responding (200 OK)"
else
    echo "❌ External endpoint not responding (HTTP $HTTP_CODE)"
fi

# Summary
echo -e "\n" 
echo "=================================="
echo "AUTO-DEPLOY READINESS SUMMARY"
echo "=================================="

# Count checks
TOTAL_CHECKS=6
PASSED=0

[ -f ".github/workflows/deploy-gke.yml" ] && ((PASSED++))
[ -f "June/services/june-orchestrator/app.py" ] && grep -q "/v1/chat" "June/services/june-orchestrator/app.py" && ((PASSED++))
[ -f "June/services/june-orchestrator/Dockerfile" ] && ((PASSED++))
[ ! -z "$CURRENT_IMAGE" ] && ((PASSED++))
[ "$POD_STATUS" = "Running" ] && ((PASSED++))
[ "$HTTP_CODE" = "200" ] && ((PASSED++))

echo "Passed: $PASSED/$TOTAL_CHECKS checks"

if [ $PASSED -eq $TOTAL_CHECKS ]; then
    echo "🎉 AUTO-DEPLOYMENT IS READY!"
    echo ""
    echo "✅ Your repo is properly configured for automatic deployment."
    echo "✅ Any push to main/master will trigger auto-deployment."
    echo "✅ The workflow will build and deploy automatically."
    echo ""
    echo "🚀 To test auto-deployment:"
    echo "   1. Make any change to June/services/june-orchestrator/"
    echo "   2. git add . && git commit -m 'test auto-deploy'"  
    echo "   3. git push origin main"
    echo "   4. Watch GitHub Actions tab for deployment progress"
elif [ $PASSED -ge 4 ]; then
    echo "⚠️  MOSTLY READY - Minor issues to fix"
    echo ""
    echo "Run the setup script to fix remaining issues:"
    echo "./setup-auto-deploy.sh"
else
    echo "❌ NEEDS SETUP - Major configuration required"
    echo ""
    echo "Run the setup script to configure auto-deployment:"
    echo "./setup-auto-deploy.sh"
fi