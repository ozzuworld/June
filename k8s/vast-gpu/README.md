# Virtual Kubelet for Vast.ai GPU Instances

A Virtual Kubelet implementation that provisions GPU instances from Vast.ai marketplace and runs Kubernetes pods on them. This enables auto-scaling GPU workloads without managing dedicated GPU nodes.

## Features

- **Real Vast.ai Provisioning**: Creates, monitors, and terminates actual GPU instances
- **Smart GPU Selection**: Matches pod requirements (GPU type, memory, price) with available offers
- **Regional Filtering**: Supports North America region filtering for compliance/latency
- **Cost Control**: Enforces price limits per pod via annotations
- **Auto-cleanup**: Terminates instances when pods are deleted
- **Health Monitoring**: Kubernetes-native health probes and node status management

## Architecture

```
Kubernetes Scheduler → Virtual Node (vast-gpu-node-python)
                     ↓
             Virtual Kubelet Pod
                     ↓
              Vast.ai API (buy/poll/delete)
                     ↓
             GPU Instance (running containers)
```

## Quick Start

### 1. Deploy Virtual Kubelet

```bash
# Create Vast.ai API key secret
kubectl create secret generic vast-api-secret \
  --from-literal=api-key=YOUR_VAST_API_KEY \
  -n kube-system

# Deploy Virtual Kubelet
kubectl apply -f deployments/virtual-kubelet-vast-python.yaml

# Verify deployment
kubectl get pods -n kube-system -l app=virtual-kubelet-vast-python
kubectl get nodes | grep vast
```

### 2. Deploy GPU Workloads

```bash
# Deploy combined STT+TTS services
kubectl apply -f k8s/vast-gpu/gpu-services-deployment.yaml

# Monitor provisioning
kubectl get pods -n june-services -l app=june-gpu-services -w
kubectl logs -n kube-system -l app=virtual-kubelet-vast-python -f
```

## GPU Service Annotations

Configure GPU requirements using pod annotations:

```yaml
metadata:
  annotations:
    # Primary GPU type to search for
    vast.ai/gpu-type: "RTX 3060"
    
    # Fallback GPU types (comma-separated)
    vast.ai/gpu-fallbacks: "RTX 3060 Ti,RTX 4060,RTX 4070,RTX 3090"
    
    # Maximum price per hour (USD)
    vast.ai/price-max: "0.30"
    
    # Geographic region filter
    vast.ai/region: "North America"
    
    # Minimum GPU memory (optional)
    vast.ai/memory: "12GB"
    
    # Disk space requirement (optional)
    vast.ai/disk: "50GB"
```

### Supported Regions

- `"North America"` - US, Canada, Mexico
- `"Europe"` - European countries
- `"Asia"` - Asian countries
- Leave empty for global search

## Instance Lifecycle

1. **Pod Scheduling**: Kubernetes schedules pod to `vast-gpu-node-python`
2. **Offer Search**: VK searches Vast.ai marketplace for matching GPU offers
3. **Instance Creation**: VK buys the best matching offer
4. **Readiness Polling**: VK waits for instance to become SSH-accessible
5. **Pod Running**: Pod status updated to Running with instance IP
6. **Cleanup**: Instance terminated when pod is deleted

## Monitoring

### Check Virtual Kubelet Status

```bash
# VK pod status and logs
kubectl get pods -n kube-system -l app=virtual-kubelet-vast-python
kubectl logs -n kube-system -l app=virtual-kubelet-vast-python --tail=50

# Virtual node status
kubectl get nodes vast-gpu-node-python
kubectl describe node vast-gpu-node-python
```

### Monitor GPU Workloads

```bash
# GPU service status
kubectl get pods -n june-services -l app=june-gpu-services
kubectl describe pod -n june-services -l app=june-gpu-services

# Check instance assignment
kubectl get pods -n june-services -o wide
```

### View Provisioning Logs

```bash
# Real-time VK logs with structured JSON
kubectl logs -n kube-system -l app=virtual-kubelet-vast-python -f | jq .

# Filter specific events
kubectl logs -n kube-system -l app=virtual-kubelet-vast-python | grep "offer match"
kubectl logs -n kube-system -l app=virtual-kubelet-vast-python | grep "Instance ready"
```

## Cost Management

### Price Optimization

1. **Monitor Current Rates**: Check Vast.ai marketplace for GPU prices
2. **Adjust Price Limits**: Update `vast.ai/price-max` annotations
3. **Use Fallback GPUs**: Configure multiple GPU types in fallbacks
4. **Regional Selection**: Choose regions with lower costs

```bash
# Check current GPU prices
curl -s "https://console.vast.ai/api/v0/bundles" | jq '.[] | select(.gpu_name | contains("RTX 3060"))'
```

### Cost Tracking

- Monitor Vast.ai dashboard for active instances
- Set up billing alerts in Vast.ai account
- Use pod resource requests to estimate costs

## Troubleshooting

### Virtual Kubelet Not Starting

```bash
# Check deployment status
kubectl get deployment -n kube-system virtual-kubelet-vast-python
kubectl describe pod -n kube-system -l app=virtual-kubelet-vast-python

# Common issues:
# 1. Missing VAST_API_KEY secret
# 2. RBAC permissions
# 3. Health probe failures
```

### Node Not Ready

```bash
# Check node conditions
kubectl describe node vast-gpu-node-python | grep -A10 Conditions

# Manual node status update
kubectl patch node vast-gpu-node-python -p '{"status":{"conditions":[{"type":"Ready","status":"True","reason":"VirtualKubeletReady"}]}}'
```

### Pods Stuck in Pending

```bash
# Check scheduling events
kubectl describe pod -n june-services PODNAME

# Common causes:
# 1. Missing tolerations for VK taints
# 2. Node not Ready
# 3. No matching GPU offers
# 4. Price limits too low
```

### No Matching GPU Offers

```bash
# Check VK logs for offer search results
kubectl logs -n kube-system -l app=virtual-kubelet-vast-python | grep "offers found"

# Solutions:
# 1. Increase vast.ai/price-max
# 2. Add more GPU types to fallbacks
# 3. Remove region restrictions
# 4. Check Vast.ai marketplace availability
```

### Instance Creation Failures

```bash
# Check instance creation logs
kubectl logs -n kube-system -l app=virtual-kubelet-vast-python | grep "buy_instance"

# Common issues:
# 1. Insufficient Vast.ai account balance
# 2. Offer no longer available
# 3. API rate limits
# 4. Instance startup timeout
```

### Health Probe Failures

```bash
# Check VK health endpoints
kubectl port-forward -n kube-system deployment/virtual-kubelet-vast-python 10255:10255
curl http://localhost:10255/healthz
curl http://localhost:10255/readyz
```

## Configuration

### Environment Variables

- `NODE_NAME`: Virtual node name (default: `vast-gpu-node-python`)
- `VAST_API_KEY`: Vast.ai API key (required)

### Resource Limits

Virtual Kubelet resource usage:
- CPU: 200m request, 1 core limit
- Memory: 512Mi request, 2Gi limit

### Health Probes

- **Readiness**: 20s initial delay, 10s interval, 3s timeout
- **Liveness**: 60s initial delay, 30s interval, 5s timeout

## Development

### Local Testing

```bash
# Build and push VK image
docker build -t ozzuworld/virtual-kubelet-vast-python:latest tools/virtual-kubelet-vast-python/
docker push ozzuworld/virtual-kubelet-vast-python:latest

# Update deployment
kubectl rollout restart deployment -n kube-system virtual-kubelet-vast-python
```

### Debug Mode

```bash
# Enable debug logging
kubectl set env deployment/virtual-kubelet-vast-python -n kube-system PYTHONPATH=/app
kubectl set env deployment/virtual-kubelet-vast-python -n kube-system RUST_LOG=debug
```

## Limitations

- Maximum 10 pods per virtual node
- Instance startup time: 2-5 minutes
- Regional availability depends on Vast.ai marketplace
- Instance persistence limited to pod lifecycle
- No persistent storage across instance recreation

## Security

- Store Vast.ai API key in Kubernetes secrets
- Use RBAC to limit VK permissions
- Network policies for pod-to-pod communication
- Regular API key rotation

## Support

For issues:
1. Check troubleshooting section above
2. Review VK logs with structured output
3. Verify Vast.ai account status and balance
4. Test GPU availability in target regions