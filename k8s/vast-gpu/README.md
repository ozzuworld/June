# Vast.ai GPU Integration for June Platform

This directory contains the configuration files needed to integrate Vast.ai GPU resources with your existing Kubernetes cluster using Virtual Kubelet.

## Architecture Overview

The integration provides:
- **Virtual Kubelet**: Presents Vast.ai instances as virtual Kubernetes nodes
- **Multi-Service Container**: Runs both STT and TTS services on a single GPU
- **Service Discovery**: Maintains FQDN accessibility (`june-stt.default.svc.cluster.local`, `june-tts.default.svc.cluster.local`)
- **Cost Optimization**: Single RTX 3060 12GB instance handles both services

## Prerequisites

1. **Vast.ai Account**: Get your API key from [Vast.ai Console](https://console.vast.ai/)
2. **Docker Registry**: Push images to your container registry
3. **Kubernetes Cluster**: Your existing cluster should be running

## Deployment Steps

### Step 1: Build and Push Multi-Service Image

```bash
# Build the multi-service container
cd June/services/june-gpu-multi
docker build -t your-registry/june-gpu-multi:latest .
docker push your-registry/june-gpu-multi:latest
```

### Step 2: Build Virtual Kubelet Provider

You'll need to implement the Virtual Kubelet provider for Vast.ai. Reference implementation:
- [RunPod Kubelet Example](https://github.com/BSVogler/k8s-runpod-kubelet)
- [Virtual Kubelet Documentation](https://virtual-kubelet.io/docs/)

```bash
# Build virtual kubelet with Vast.ai provider
docker build -t your-registry/virtual-kubelet-vast:latest .
docker push your-registry/virtual-kubelet-vast:latest
```

### Step 3: Create Secrets and Config

```bash
# Copy template and fill in your values
cp secrets-template.yaml secrets.yaml
# Edit secrets.yaml with your actual values

# Encode your secrets
echo -n "your-vast-api-key" | base64
echo -n "your-livekit-api-key" | base64
echo -n "your-livekit-api-secret" | base64
echo -n "your-bearer-token" | base64

# Apply secrets
kubectl apply -f secrets.yaml
```

### Step 4: Deploy RBAC and Virtual Kubelet

```bash
# Deploy RBAC permissions
kubectl apply -f rbac.yaml

# Update virtual-kubelet-deployment.yaml with your registry
# Then deploy Virtual Kubelet
kubectl apply -f virtual-kubelet-deployment.yaml
```

### Step 5: Deploy GPU Services

```bash
# Update gpu-services-deployment.yaml with your registry
kubectl apply -f gpu-services-deployment.yaml

# Deploy services
kubectl apply -f services.yaml
```

## Verification

```bash
# Check if virtual node is registered
kubectl get nodes
# Should show: vast-gpu-node-1

# Check pod scheduling
kubectl get pods -o wide
# GPU services should be on vast-gpu-node-1

# Check service endpoints
kubectl get endpoints june-stt june-tts
# Should show Vast.ai external IP and ports

# Test service connectivity
kubectl run test-pod --image=curlimages/curl --rm -it -- sh
# Inside pod:
curl http://june-stt.default.svc.cluster.local:8001/healthz
curl http://june-tts.default.svc.cluster.local:8000/healthz
```

## Cost Optimization

- **Single Instance**: RTX 3060 12GB (~$0.20-0.40/hour)
- **Shared GPU**: Both STT (~3GB) and TTS (~5GB) fit in 12GB
- **Auto-scaling**: Pods scale down when not needed

## Monitoring

```bash
# Check Virtual Kubelet logs
kubectl logs -n kube-system deployment/virtual-kubelet-vast

# Check GPU service logs
kubectl logs deployment/june-gpu-services -c june-multi-gpu

# Monitor GPU usage (if available)
kubectl exec deployment/june-gpu-services -- nvidia-smi
```

## Troubleshooting

### Virtual Kubelet Issues
- Check RBAC permissions
- Verify Vast.ai API key
- Review Virtual Kubelet logs

### Pod Scheduling Issues
- Check node taints and tolerations
- Verify node selector labels
- Review resource requests

### Service Discovery Issues
- Check endpoint updates
- Verify service annotations
- Test DNS resolution

### GPU Issues
- Verify CUDA drivers in container
- Check GPU resource allocation
- Monitor memory usage

## Next Steps

1. **Implement Virtual Kubelet Provider**: Custom provider for Vast.ai API
2. **Add Monitoring**: Prometheus metrics for GPU usage
3. **Implement Auto-scaling**: HPA based on queue depth
4. **Add Health Checks**: Robust health monitoring
5. **Security Hardening**: Network policies and secrets management

## References

- [Virtual Kubelet Documentation](https://virtual-kubelet.io/)
- [Vast.ai API Documentation](https://vast.ai/docs/)
- [Kubernetes GPU Scheduling](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/)
- [Multi-Container Pods](https://kubernetes.io/docs/concepts/workloads/pods/)