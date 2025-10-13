#!/bin/bash
# June Platform Setup Script
# Makes installation script executable and shows usage

echo "June Platform - Setting up installation..."

# Make scripts executable
chmod +x install.sh
chmod +x test-stunner.sh
chmod +x setup.sh

echo "✅ Installation script is now executable"
echo ""
echo "June Platform - Complete Installation:"
echo "  ./install.sh    - Install everything (K8s + June + LiveKit + STUNner)"
echo ""
echo "For fresh VM deployment, run:"
echo "  sudo ./install.sh"
echo ""
echo "This single script will install:"
echo "  ✓ Kubernetes cluster"
echo "  ✓ Infrastructure (ingress, cert-manager)"
echo "  ✓ June Platform services (API, IDP, STT, TTS)"
echo "  ✓ LiveKit WebRTC server"
echo "  ✓ STUNner TURN server"
echo "  ✓ SSL certificates"
echo ""
echo "Total installation time: ~10-15 minutes on a fresh VM"
echo ""
echo "See MIGRATION.md if upgrading from old Janus setup."