#!/bin/bash
# Test script to verify Vast.ai CLI functionality in container

echo "=== Testing Vast.ai CLI Connection ==="

# Check if vastai CLI is available
echo "Checking vastai CLI installation..."
vastai --version || echo "vastai CLI not found"

# Check SSL certificates
echo "\nChecking SSL certificate configuration..."
echo "SSL_CERT_FILE: $SSL_CERT_FILE"
echo "REQUESTS_CA_BUNDLE: $REQUESTS_CA_BUNDLE"
echo "CURL_CA_BUNDLE: $CURL_CA_BUNDLE"

# Test API key
echo "\nChecking API key configuration..."
if [ -f ~/.vastai_api_key ]; then
    echo "API key file exists: ~/.vastai_api_key"
else
    echo "API key file not found"
fi

if [ -n "$VAST_API_KEY" ]; then
    echo "VAST_API_KEY environment variable is set"
else
    echo "VAST_API_KEY environment variable not set"
fi

# Test connection to Vast.ai API
echo "\nTesting HTTPS connection to Vast.ai..."
curl -s -I https://console.vast.ai/ | head -1 || echo "Connection failed"

# Test vastai CLI commands
echo "\nTesting vastai CLI commands..."
echo "Attempting to get user info..."
vastai show user 2>&1 | head -5

echo "\nAttempting to search for offers..."
vastai search offers "rentable=true verified=true rented=false dph<=0.50" 2>&1 | head -5

echo "\n=== Test Complete ==="