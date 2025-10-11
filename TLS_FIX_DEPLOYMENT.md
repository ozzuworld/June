# TLS Certificate Fix Deployment Guide

This guide explains how to deploy the fix for the fundamental TLS certificate issue in your June platform.

## The Problem

Your wildcard certificate issue had two core components:

1. **Missing TLS Specification in Ingress**: The ingress resource lacked a proper `spec.tls` section with concrete host names and secret reference
2. **Namespace Isolation of Secrets**: The wildcard certificate secret existed in the `cert-manager` namespace, but ingress was in `june-services` namespace

## The Solution

Two files have been created to fix this:

- `k8s/certificate-fix.yaml` - Creates the certificate directly in june-services namespace
- `k8s/complete-manifests-fixed.yaml` - Complete manifests with fixed TLS configuration

## Deployment Steps

### Option 1: Apply the Complete Fixed Manifests

```bash
# Apply the fixed complete manifests
kubectl apply -f k8s/complete-manifests-fixed.yaml

# Check certificate creation
kubectl get certificate -n june-services

# Check certificate secret
kubectl get secret ozzu-world-wildcard-tls -n june-services

# Check ingress status
kubectl get ingress june-ingress -n june-services
```

### Option 2: Apply Just the Certificate Fix

If you prefer to keep your existing manifests and just fix the certificate:

```bash
# Apply the certificate fix
kubectl apply -f k8s/certificate-fix.yaml

# Update your existing ingress to reference the correct secret
kubectl patch ingress june-ingress -n june-services -p '{
  "spec": {
    "tls": [{
      "hosts": [
        "api.ozzu.world",
        "idp.ozzu.world", 
        "stt.ozzu.world",
        "tts.ozzu.world",
        "turn.ozzu.world"
      ],
      "secretName": "ozzu-world-wildcard-tls"
    }]
  }
}'
```

## Verification Steps

### 1. Check Certificate Status
```bash
kubectl describe certificate ozzu-world-wildcard-cert -n june-services
```

Should show:
- `Status: Ready`
- `Events: Certificate issued successfully`

### 2. Check Secret Creation
```bash
kubectl get secret ozzu-world-wildcard-tls -n june-services -o yaml
```

Should contain `tls.crt` and `tls.key` data.

### 3. Check Ingress Configuration
```bash
kubectl describe ingress june-ingress -n june-services
```

Should show:
- TLS section with all your domains
- Correct secret name: `ozzu-world-wildcard-tls`
- Backend services properly configured

### 4. Test HTTPS Endpoints
```bash
# Test each service
curl -I https://api.ozzu.world/healthz
curl -I https://idp.ozzu.world/health/ready
curl -I https://stt.ozzu.world/healthz  
curl -I https://tts.ozzu.world/healthz
```

All should return:
- `HTTP/2 200` (or appropriate response)
- Valid SSL certificate
- No certificate errors

## Key Changes Made

### 1. Certificate Resource
- Creates `Certificate` resource directly in `june-services` namespace
- Uses `letsencrypt-prod` ClusterIssuer
- Generates secret `ozzu-world-wildcard-tls` in correct namespace

### 2. Ingress Updates
- **Fixed TLS section**: Concrete host names instead of templates
- **Correct secretName**: `ozzu-world-wildcard-tls` 
- **Enabled SSL redirect**: Forces HTTPS for all traffic
- **Namespace-local secret**: Ingress can now access the certificate

### 3. Security Improvements
- Enabled `ssl-redirect` and `force-ssl-redirect`
- All traffic now properly encrypted
- Certificate automatically renewed by cert-manager

## Troubleshooting

### Certificate Not Ready
```bash
# Check certificate status
kubectl describe certificate ozzu-world-wildcard-cert -n june-services

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager

# Check challenge status
kubectl get challenges -n june-services
```

### Ingress Not Working
```bash
# Check ingress controller logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller

# Verify ingress class
kubectl get ingress june-ingress -n june-services -o yaml
```

### DNS Issues
Ensure all domains point to your ingress controller's external IP:
```bash
# Get ingress IP
kubectl get svc -n ingress-nginx ingress-nginx-controller

# Test DNS resolution
nslookup api.ozzu.world
nslookup idp.ozzu.world
```

## Files Created

1. [`k8s/certificate-fix.yaml`](k8s/certificate-fix.yaml) - Standalone certificate fix
2. [`k8s/complete-manifests-fixed.yaml`](k8s/complete-manifests-fixed.yaml) - Complete fixed manifests
3. `TLS_FIX_DEPLOYMENT.md` - This deployment guide

Choose the deployment option that best fits your current setup and operational preferences.