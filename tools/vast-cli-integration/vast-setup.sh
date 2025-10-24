#!/bin/bash

# Vast.ai CLI Setup Script
# This script properly installs and configures the vast.ai CLI

set -euo pipefail

echo "Setting up Vast.ai CLI..."

# Install vast.ai CLI
echo "Installing vastai CLI..."
pip3 install vastai

# Verify installation
if ! command -v vastai &> /dev/null; then
    echo "ERROR: vastai CLI not found in PATH"
    exit 1
fi

echo "✓ vastai CLI installed successfully"

# Check if API key is provided
if [ -z "${VAST_API_KEY:-}" ]; then
    echo "ERROR: VAST_API_KEY environment variable is required"
    echo "Please set your Vast.ai API key:"
    echo "export VAST_API_KEY='your_api_key_here'"
    exit 1
fi

# Set API key
echo "Setting up API key..."
vastai set api-key "${VAST_API_KEY}"

# Verify API key works
echo "Verifying API key..."
if vastai show user --raw > /dev/null 2>&1; then
    echo "✓ API key configured successfully"
else
    echo "ERROR: API key verification failed"
    exit 1
fi

echo "✓ Vast.ai CLI setup complete"