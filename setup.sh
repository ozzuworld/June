#!/bin/bash
# June Platform Setup Script
# Makes all installation scripts executable

echo "June Platform - Setting up installation scripts..."

# Make scripts executable
chmod +x install.sh
chmod +x install-clean.sh
chmod +x install-livekit.sh
chmod +x test-stunner.sh
chmod +x setup.sh

echo "✅ Installation scripts are now executable"
echo ""
echo "Available installation options:"
echo "  ./install-clean.sh    - Core services only (recommended)"
echo "  ./install-livekit.sh  - Add LiveKit + STUNner WebRTC"
echo "  ./install.sh          - Legacy full installation (includes old Janus)"
echo ""
echo "For new deployments, use:"
echo "  sudo ./install-clean.sh"
echo "  sudo ./install-livekit.sh"
echo ""
echo "See MIGRATION.md for detailed migration instructions."