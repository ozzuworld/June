# Headscale Integration for June Platform

**Simple Headscale-based networking for connecting external GPU containers to Kubernetes cluster**

## Overview

This directory contains a **simplified Headscale integration** that connects your vast.ai GPU containers to your Kubernetes cluster through your private Headscale VPN.

**What this replaces:**
- ❌ Complex Tailscale.com OAuth setup
- ❌ Tailscale Kubernetes operator 
- ❌ Per-service proxy configurations
- ✅ Simple subnet router that exposes entire cluster

## Quick Setup

### 1. Create Headscale API Key

```bash
# Create API key on your Headscale server
kubectl -n headscale exec deployment/headscale -- headscale apikey create --expiration=365d k8s-subnet-router
```

### 2. Deploy Subnet Router

```bash
# Update the API key in the configuration
sed -i 's/REPLACE_WITH_YOUR_HEADSCALE_API_KEY/YOUR_ACTUAL_API_KEY/' k8s/tailscale/headscale-integration.yaml

# Deploy the subnet router
kubectl apply -f k8s/tailscale/headscale-integration.yaml

# Verify it's running
kubectl -n kube-system get pods | grep headscale
kubectl -n kube-system logs deployment/headscale-subnet-router
```

### 3. Connect External GPU Container

Your vast.ai GPU container should already be connected to Headscale. Verify with:

```bash
# From GPU container
tailscale status  # Should show k8s-cluster device

# Test cluster connectivity
curl http://10.104.215.160:8080/healthz  # Direct to service IP
```

## Service Access

Once the subnet router is working, your GPU containers can access Kubernetes services directly:

```bash
# Orchestrator service
ORCHESTRATOR_URL="http://10.104.215.160:8080"

# Get other service IPs
kubectl -n june-services get svc -o wide
kubectl -n livekit get svc -o wide
```

## Configuration

Update your GPU container services to use cluster IPs:

```python
# In your Python services
ORCHESTRATOR_URL = "http://10.104.215.160:8080"  # Direct cluster IP
LIVEKIT_URL = "ws://LIVEKIT_CLUSTER_IP:7880"     # Get from kubectl
```

## Troubleshooting

```bash
# Check subnet router status
kubectl -n kube-system logs deployment/headscale-subnet-router

# Verify Headscale connection
kubectl -n kube-system exec deployment/headscale-subnet-router -- tailscale status

# Test connectivity from GPU container
ping 10.96.0.1  # Kubernetes DNS
curl http://10.104.215.160:8080/healthz  # Orchestrator
```

## Security

- All traffic stays within your private Headscale network
- No internet exposure of services
- Kubernetes cluster networks (10.96.0.0/12, 10.244.0.0/16) are advertised to Headscale
- Only devices in your Headscale network can access cluster services

## Architecture

```
vast.ai GPU Container → Headscale VPN → Subnet Router → K8s Services
     (100.64.0.5)    →    (mesh)    →  (k8s-cluster) →  (10.96.x.x)
```

## Old Files (Can be Removed)

These files were for Tailscale.com integration and are no longer needed:
- `tailscale-operator.yaml` (Tailscale.com operator)
- `tailscale-secret.yaml.example` (OAuth credentials)
- `june-orchestrator-tailscale.yaml` (Per-service proxies)
- `livekit-tailscale.yaml` (Per-service proxies)
- `june-gpu-multi-config.yaml` (ConfigMap approach)
- `subnet-router-fix.yaml` (Previous attempt)

Only keep:
- ✅ `headscale-integration.yaml` (This file)
- ✅ `README.md` (This README)