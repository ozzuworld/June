# OpenCTI Deployment for June Platform

This directory contains the Kubernetes deployment configuration for OpenCTI (Open Cyber Threat Intelligence) platform as part of the June platform infrastructure.

## Overview

OpenCTI is deployed using the official Helm chart from `devops-ia/helm-opencti`. The configuration is optimized for integration with the existing June platform infrastructure, including proper SSL certificates, ingress configuration, and resource allocation.

## Files

- `install-opencti.sh` - Automated deployment script with troubleshooting capabilities
- `values-production.yaml` - Main production configuration (uses OpenSearch)
- `values-fixed.yaml` - Fallback configuration for existing OpenSearch services

## Quick Start

### Prerequisites

- Kubernetes cluster with `kubectl` configured
- Helm 3.x installed
- Nginx ingress controller running
- cert-manager for SSL certificates
- Local storage class configured

### Deploy OpenCTI

```bash
# Make the script executable
chmod +x k8s/opencti/install-opencti.sh

# Deploy OpenCTI
./k8s/opencti/install-opencti.sh
```

### Access OpenCTI

After successful deployment:
- **URL**: https://opencti.ozzu.world
- **Email**: admin@ozzu.world
- **Password**: OpenCTI2024! (change in production)
- **Admin Token**: Generated automatically (shown in deployment output)

## Configuration Details

### Search Engine Configuration

OpenCTI requires a search engine (Elasticsearch or OpenSearch). The configuration automatically:

1. **Primary approach** (`values-production.yaml`): Deploys OpenSearch as part of the Helm chart
2. **Fallback approach** (`values-fixed.yaml`): Connects to existing `opensearch-cluster-master` service

The deployment script automatically detects existing OpenSearch services and chooses the appropriate configuration.

### Key Configuration Parameters

#### OpenSearch Settings
```yaml
opensearch:
  enabled: true
  singleNode: true  # Single node for resource efficiency
  config:
    opensearch.yml: |
      cluster.name: opencti-cluster
      discovery.type: single-node
      plugins.security.disabled: true
```

#### OpenCTI Application Environment
```yaml
app:
  env:
    ELASTICSEARCH__URL: "http://opencti-opensearch:9200"
    ELASTICSEARCH__ENGINE_SELECTOR: "opensearch"
    ELASTICSEARCH__ENGINE_CHECK: "false"
```

### Resource Allocation

- **OpenCTI App**: 500m CPU, 2Gi RAM (requests) / 1000m CPU, 4Gi RAM (limits)
- **OpenSearch**: 500m CPU, 3Gi RAM (requests) / 1000m CPU, 4Gi RAM (limits)
- **Redis**: 100m CPU, 256Mi RAM (requests) / 200m CPU, 512Mi RAM (limits)
- **RabbitMQ**: 200m CPU, 512Mi RAM (requests) / 500m CPU, 1Gi RAM (limits)
- **MinIO**: 200m CPU, 512Mi RAM (requests) / 500m CPU, 1Gi RAM (limits)

### Storage Configuration

- **OpenSearch**: 50Gi persistent volume
- **Redis**: 5Gi persistent volume
- **RabbitMQ**: 10Gi persistent volume
- **MinIO**: 100Gi persistent volume

All use `local-storage` storage class to match existing infrastructure.

## Troubleshooting

### Common Issues

#### 1. "Search engine seems down" Error

**Symptoms:**
```
ConfigurationError: Search engine seems down
getaddrinfo ENOTFOUND release-name-elasticsearch
```

**Solution:**
This indicates OpenCTI cannot connect to the search engine. The deployment script handles this automatically, but if you encounter it:

```bash
# Check OpenSearch service status
kubectl get services -n opencti | grep -E "(opensearch|elasticsearch)"

# Use troubleshooting script
./k8s/opencti/install-opencti.sh --troubleshoot

# Try fallback configuration
helm upgrade opencti opencti/opencti -f k8s/opencti/values-fixed.yaml -n opencti
```

#### 2. Pods in CrashLoopBackOff

**Check pod status:**
```bash
kubectl get pods -n opencti
kubectl logs <pod-name> -n opencti
```

**Common causes:**
- Resource constraints
- Missing dependencies
- Configuration errors

#### 3. Worker Init Containers Failing

**Symptoms:**
```
opencti-worker-xxx   0/1   Init:0/1   18 (6m30s ago)   122m
```

**Solution:**
```bash
# Check init container logs
kubectl logs <worker-pod> -c <init-container> -n opencti

# Usually indicates OpenCTI server isn't ready yet
# Wait for server to be fully operational
```

### Useful Commands

```bash
# Show deployment status
./k8s/opencti/install-opencti.sh --status

# Show recent logs
./k8s/opencti/install-opencti.sh --logs

# Full troubleshooting information
./k8s/opencti/install-opencti.sh --troubleshoot

# Test OpenSearch connectivity
kubectl run test-curl --rm -i --restart=Never --image=curlimages/curl:latest -n opencti -- curl -s http://opensearch-cluster-master:9200

# Check OpenCTI environment variables
kubectl exec -it <opencti-pod> -n opencti -- env | grep ELASTICSEARCH

# Monitor pod startup
kubectl get pods -n opencti -w
```

### Service Discovery

The deployment automatically discovers existing services:

```bash
# List all services in namespace
kubectl get services -n opencti

# Check service endpoints
kubectl get endpoints -n opencti

# Describe specific service
kubectl describe service opensearch-cluster-master -n opencti
```

### Configuration Validation

```bash
# Validate Helm values
helm template opencti opencti/opencti -f k8s/opencti/values-production.yaml --debug

# Check deployed configuration
kubectl get configmap -n opencti
kubectl describe configmap <configmap-name> -n opencti
```

## Maintenance

### Upgrades

```bash
# Update Helm repository
helm repo update

# Upgrade OpenCTI
helm upgrade opencti opencti/opencti -f k8s/opencti/values-production.yaml -n opencti
```

### Backup

```bash
# Backup Helm values
helm get values opencti -n opencti > backup-values.yaml

# Backup persistent volumes (implement based on your storage solution)
```

### Cleanup

```bash
# Remove deployment
./k8s/opencti/install-opencti.sh --cleanup

# Or manual cleanup
helm uninstall opencti -n opencti
kubectl delete namespace opencti
```

## Security Considerations

1. **Change default passwords** in production
2. **Enable authentication** for Redis and other services as needed
3. **Configure network policies** if required
4. **Use proper RBAC** for service accounts
5. **Implement backup strategy** for persistent data

## Integration with June Platform

OpenCTI integrates with the June platform through:

- **Shared SSL certificates** (ozzu-world-wildcard-tls)
- **Common ingress controller** (nginx)
- **Consistent storage classes** (local-storage)
- **Unified monitoring and logging** (if implemented)

## Support

For issues specific to this deployment:
1. Use the troubleshooting commands above
2. Check the deployment logs
3. Review the Helm chart documentation: https://artifacthub.io/packages/helm/helm-opencti/opencti
4. Consult OpenCTI documentation: https://docs.opencti.io/

## Version Information

- **OpenCTI Version**: 6.8.6
- **Helm Chart**: devops-ia/helm-opencti (latest)
- **OpenSearch**: Single-node deployment
- **Kubernetes**: Compatible with 1.20+