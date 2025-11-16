#!/bin/bash
# Debug script for Keycloak SSO issues

source /home/kazuma.ozzu/June/config.env

echo "🔍 Debugging Keycloak SSO Setup"
echo "================================"
echo ""

echo "1️⃣ Checking Keycloak pod status..."
kubectl get pods -n june-services | grep -i keycloak
echo ""

echo "2️⃣ Checking if Keycloak is accessible internally..."
KEYCLOAK_POD=$(kubectl get pod -n june-services -l app=june-idp -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$KEYCLOAK_POD" ]; then
    echo "Keycloak pod: $KEYCLOAK_POD"
    kubectl exec -n june-services "$KEYCLOAK_POD" -- curl -s http://localhost:8080/health 2>/dev/null || echo "Health check failed"
else
    echo "❌ Keycloak pod not found with label app=june-idp"
    echo ""
    echo "Searching for any Keycloak-related pods..."
    kubectl get pods -n june-services -o wide
fi
echo ""

echo "3️⃣ Testing Keycloak URL: $KEYCLOAK_URL"
curl -k -s "$KEYCLOAK_URL/realms/master/.well-known/openid-configuration" | jq -r '.issuer' 2>/dev/null || echo "❌ Cannot reach Keycloak at $KEYCLOAK_URL"
echo ""

echo "4️⃣ Testing admin token request..."
TOKEN_RESPONSE=$(curl -k -s -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$KEYCLOAK_ADMIN_USER" \
  -d "password=$KEYCLOAK_ADMIN_PASSWORD" \
  -d "grant_type=password" \
  -d "client_id=admin-cli")

echo "Response (first 200 chars):"
echo "$TOKEN_RESPONSE" | head -c 200
echo ""
echo ""

if echo "$TOKEN_RESPONSE" | jq -e '.access_token' >/dev/null 2>&1; then
    echo "✅ Token obtained successfully"
else
    echo "❌ Failed to get token. Full response:"
    echo "$TOKEN_RESPONSE" | jq . 2>/dev/null || echo "$TOKEN_RESPONSE"
fi
echo ""

echo "5️⃣ Checking Keycloak service..."
kubectl get svc -n june-services | grep -i keycloak
echo ""

echo "6️⃣ Checking Keycloak ingress..."
kubectl get ingress -n june-services | grep -i keycloak
echo ""

echo "7️⃣ Config values being used:"
echo "KEYCLOAK_URL: $KEYCLOAK_URL"
echo "KEYCLOAK_REALM: $KEYCLOAK_REALM"
echo "KEYCLOAK_ADMIN_USER: $KEYCLOAK_ADMIN_USER"
echo "KEYCLOAK_ADMIN_PASSWORD: [hidden]"
echo ""

echo "8️⃣ Checking Keycloak logs (last 20 lines)..."
if [ -n "$KEYCLOAK_POD" ]; then
    kubectl logs -n june-services "$KEYCLOAK_POD" --tail=20
else
    echo "No Keycloak pod to check logs"
fi
