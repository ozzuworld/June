# Enhanced Virtual Kubelet Setup & Installation Guide

## Quick Start (Development Mode - Single Instance)

### Prerequisites

1. **Kubernetes Cluster**: Running cluster with kubectl access
2. **Vast.ai Account**: API key from [console.vast.ai](https://console.vast.ai)
3. **Docker**: For building custom images (optional)

### Step 1: Prepare Credentials

Create the Vast.ai API key secret:

```bash
# Replace YOUR_API_KEY with your actual Vast.ai API key
kubectl create secret generic vast-api-credentials \
  --from-literal=api-key=YOUR_API_KEY \
  -n kube-system
```

### Step 2: Deploy Enhanced Virtual Kubelet

```bash
# Apply the enhanced deployment
kubectl apply -f enhanced_deployment.yaml

# Check deployment status
kubectl get pods -n kube-system -l app=virtual-kubelet-vast
kubectl logs -f deployment/virtual-kubelet-vast-enhanced -n kube-system
```

### Step 3: Verify Node Registration

```bash
# Check if the virtual node is registered
kubectl get nodes
kubectl describe node vast-gpu-node-python
```

You should see a node with labels:
- `type=virtual-kubelet`
- `vast.ai/gpu-node=true` 
- `vast.ai/provider=vast-python`

### Step 4: Test with Sample Workload

```bash
# Deploy the sample GPU workload (included in enhanced-deployment.yaml)
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-gpu-workload
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: test-gpu-workload
  template:
    metadata:
      labels:
        app: test-gpu-workload
      annotations:
        vast.ai/gpu-type: "RTX 4060"
        vast.ai/price-max: "0.25"
        vast.ai/region: "US"
        vast.ai/disk: "50"
    spec:
      nodeName: vast-gpu-node-python
      tolerations:
      - key: "virtual-kubelet.io/provider"
        operator: "Equal"
        value: "vast-ai"
        effect: "NoSchedule"
      containers:
      - name: gpu-test
        image: nvidia/cuda:12.0-base-ubuntu22.04
        command: ["sleep", "3600"]
        resources:
          requests:
            nvidia.com/gpu: 1
          limits:
            nvidia.com/gpu: 1
EOF
```

### Step 5: Monitor Deployment

```bash
# Watch pod creation and status
kubectl get pods -w

# Check virtual kubelet logs
kubectl logs -f deployment/virtual-kubelet-vast-enhanced -n kube-system

# Check detailed health status
kubectl exec -n kube-system deployment/virtual-kubelet-vast-enhanced -- curl localhost:10255/health
```

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VAST_API_KEY` | - | **Required**: Your Vast.ai API key |
| `MAX_INSTANCES` | `1` | Max concurrent instances (keep at 1 for dev) |
| `RATE_LIMIT_RPM` | `30` | API requests per minute limit |
| `DEFAULT_GPU_TYPE` | `RTX 4060` | Default GPU when not specified |
| `REGION_PREFERENCE` | `US` | Preferred deployment region |
| `FORCE_GPU_TYPE` | - | Override GPU type for all deployments |
| `FORCE_IMAGE` | - | Override container image for all instances |
| `FORCE_PRICE_MAX` | - | Override max price for all instances |

### Pod Annotations

Configure individual workloads using annotations:

```yaml
annotations:
  vast.ai/gpu-type: "RTX 4060"           # Primary GPU type to search for
  vast.ai/gpu-fallbacks: "RTX 3060, RTX 4070"  # Comma-separated fallback GPUs
  vast.ai/price-max: "0.30"             # Maximum price per hour (USD)
  vast.ai/region: "US"                   # Deployment region (US, EU, etc.)
  vast.ai/disk: "100"                    # Disk size in GB
  vast.ai/image: "pytorch/pytorch:latest" # Override container image
  vast.ai/env: "-p 8080:8080 --privileged"  # Additional Docker arguments
  vast.ai/onstart-cmd: "nvidia-smi"     # Command to run on instance startup
```

## Advanced Configuration

### Custom GPU Types

```bash
# Set environment override for all deployments
kubectl patch deployment virtual-kubelet-vast-enhanced -n kube-system -p '
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "virtual-kubelet-vast",
            "env": [
              {
                "name": "FORCE_GPU_TYPE",
                "value": "RTX 4090"
              },
              {
                "name": "FORCE_PRICE_MAX", 
                "value": "0.75"
              }
            ]
          }
        ]
      }
    }
  }
}'
```

### Regional Deployment

```bash
# Update ConfigMap for EU deployment preference
kubectl patch configmap virtual-kubelet-vast-config -n kube-system -p '
{
  "data": {
    "region-preference": "EU",
    "default-gpu-type": "RTX 4070"
  }
}'

# Restart deployment to pick up changes
kubectl rollout restart deployment/virtual-kubelet-vast-enhanced -n kube-system
```

### Scaling Configuration

For production use (change max-instances):

```bash
# Update to allow 3 concurrent instances
kubectl patch configmap virtual-kubelet-vast-config -n kube-system -p '
{
  "data": {
    "max-instances": "3"
  }
}'

kubectl rollout restart deployment/virtual-kubelet-vast-enhanced -n kube-system
```

## Monitoring & Troubleshooting

### Health Checks

```bash
# Basic health check
kubectl exec -n kube-system deployment/virtual-kubelet-vast-enhanced -- curl localhost:10255/healthz

# Detailed status
kubectl exec -n kube-system deployment/virtual-kubelet-vast-enhanced -- curl -s localhost:10255/health | jq

# Prometheus metrics
kubectl exec -n kube-system deployment/virtual-kubelet-vast-enhanced -- curl localhost:10255/metrics
```

### Logs Analysis

```bash
# Follow real-time logs
kubectl logs -f deployment/virtual-kubelet-vast-enhanced -n kube-system

# Get logs with timestamps
kubectl logs deployment/virtual-kubelet-vast-enhanced -n kube-system --timestamps

# Filter for specific events
kubectl logs deployment/virtual-kubelet-vast-enhanced -n kube-system | grep "Creating pod"
kubectl logs deployment/virtual-kubelet-vast-enhanced -n kube-system | grep "ERROR"
```

### Common Issues & Solutions

#### 1. Pod Stuck in Pending

```bash
# Check node status
kubectl describe node vast-gpu-node-python

# Check pod events
kubectl describe pod <pod-name>

# Check tolerations
kubectl get pod <pod-name> -o yaml | grep -A 5 tolerations
```

**Solution**: Ensure pod has correct toleration:
```yaml
tolerations:
- key: "virtual-kubelet.io/provider"
  operator: "Equal" 
  value: "vast-ai"
  effect: "NoSchedule"
```

#### 2. Instance Creation Failures

```bash
# Check virtual kubelet logs for error details
kubectl logs deployment/virtual-kubelet-vast-enhanced -n kube-system | grep -A 5 -B 5 "Failed"
```

**Common causes**:
- Invalid API key: Check secret configuration
- No available GPUs: Adjust GPU type or price limit
- Rate limiting: Wait and retry
- Region unavailability: Try different region

#### 3. API Rate Limiting

```bash
# Check current rate limit status
kubectl exec -n kube-system deployment/virtual-kubelet-vast-enhanced -- curl -s localhost:10255/health | jq '.metrics.error_counts'
```

**Solution**: Reduce rate limit or wait:
```bash
kubectl patch configmap virtual-kubelet-vast-config -n kube-system -p '
{
  "data": {
    "rate-limit-rpm": "20"
  }
}'
```

#### 4. Network Connectivity Issues

```bash
# Test Vast.ai API connectivity from pod
kubectl exec -n kube-system deployment/virtual-kubelet-vast-enhanced -- curl -I https://console.vast.ai/
```

**Solution**: Check firewall rules and DNS resolution.

### Performance Monitoring

```bash
# Monitor resource usage
kubectl top pod -n kube-system -l app=virtual-kubelet-vast

# Check instance creation metrics
kubectl exec -n kube-system deployment/virtual-kubelet-vast-enhanced -- curl -s localhost:10255/metrics | grep vast_instance
```

## Development & Testing

### Running Tests

```bash
# Run the test suite
kubectl cp test-suite.py kube-system/<pod-name>:/tmp/
kubectl exec -n kube-system <pod-name> -- python /tmp/test-suite.py
```

### Building Custom Image

```bash
# Build and push custom image
docker build -f enhanced_dockerfile -t ghcr.io/ozzuworld/virtual-kubelet-vast:dev .
docker push ghcr.io/ozzuworld/virtual-kubelet-vast:dev

# Update deployment to use custom image
kubectl patch deployment virtual-kubelet-vast-enhanced -n kube-system -p '
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "virtual-kubelet-vast",
            "image": "ghcr.io/ozzuworld/virtual-kubelet-vast:dev"
          }
        ]
      }
    }
  }
}'
```

### Local Development

```bash
# Run locally with kubectl proxy
kubectl proxy --port=8080 &

# Set environment variables
export VAST_API_KEY="your-api-key"
export KUBECONFIG="$HOME/.kube/config"
export NODE_NAME="vast-gpu-node-local"

# Run enhanced main
python enhanced_main.py
```

## Security Considerations

1. **API Key Management**: Store in Kubernetes secrets, rotate regularly
2. **Network Policies**: Restrict outbound traffic to Vast.ai API only
3. **RBAC**: Use minimal required permissions
4. **Container Security**: Run as non-root user, read-only filesystem

### Example Network Policy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: virtual-kubelet-vast-netpol
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      app: virtual-kubelet-vast
  policyTypes:
  - Egress
  egress:
  - to: []
    ports:
    - protocol: TCP
      port: 443  # HTTPS to Vast.ai API
  - to:
    - namespaceSelector:
        matchLabels:
          name: kube-system
    ports:
    - protocol: TCP
      port: 443  # Kubernetes API
```

## Production Checklist

Before moving to production:

- [ ] **Security Review**: API keys, RBAC, network policies
- [ ] **Resource Limits**: Set appropriate CPU/memory limits
- [ ] **Monitoring**: Set up alerting for failures
- [ ] **Backup**: Document configuration and recovery procedures
- [ ] **Cost Controls**: Set budget alerts in Vast.ai console
- [ ] **Testing**: Validate with production workloads
- [ ] **Documentation**: Update team runbooks

## Support & Contributing

- **Issues**: Report bugs or feature requests in GitHub
- **Logs**: Always include full logs when reporting issues
- **Monitoring**: Use health endpoints for operational monitoring
- **Updates**: Follow semantic versioning for deployments

This enhanced virtual kubelet provides a robust foundation for running GPU workloads on Vast.ai while maintaining development safety with the single-instance limit.