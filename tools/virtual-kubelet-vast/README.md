# Virtual Kubelet Vast.ai Provider

A Virtual Kubelet provider that integrates Kubernetes with Vast.ai GPU instances for the June platform.

## Overview

This provider allows Kubernetes to schedule pods with GPU requirements directly onto Vast.ai instances, providing:

- **Cost-effective GPU access** - RTX 3060 instances ~$0.20-0.40/hour
- **North America optimization** - Prioritizes US/CA regions for low latency
- **Automatic instance management** - Launches, monitors, and terminates instances
- **Service discovery** - Updates Kubernetes service endpoints automatically
- **Multi-service support** - Runs both STT and TTS on shared GPU

## Features

### Instance Selection
- **Smart scoring algorithm** prioritizing North America regions
- **Cost optimization** with configurable price limits
- **Performance filtering** by reliability, bandwidth, and latency
- **Fallback regions** when primary locations unavailable

### Pod Lifecycle Management
- **Create**: Launches Vast.ai instance with pod's container
- **Monitor**: Continuously checks instance health and status
- **Update**: Limited support (recreates instance if needed)
- **Delete**: Terminates instance and cleans up resources

### Service Integration
- **Endpoint management** for june-stt and june-tts services
- **Port mapping** from container ports to external Vast.ai ports
- **Health monitoring** of both STT (8001) and TTS (8000) services
- **FQDN preservation** - `june-stt.default.svc.cluster.local` works seamlessly

## Quick Start

### Prerequisites

1. **Vast.ai account** with API key from [console.vast.ai](https://console.vast.ai/)
2. **Kubernetes cluster** with Virtual Kubelet RBAC applied
3. **Container registry** access (Docker Hub recommended)

### Build and Deploy

```bash
# Clone and build
cd tools/virtual-kubelet-vast

# Build and push image
make docker REGISTRY=ozzuworld
make push REGISTRY=ozzuworld

# Deploy to cluster
make deploy REGISTRY=ozzuworld

# Monitor startup
make dev-logs
```

### Verify Deployment

```bash
# Check if virtual node is registered
kubectl get nodes
# Should show: vast-gpu-node-na-1

# Check GPU pod scheduling
kubectl get pods -l app=june-gpu-services -o wide
# Should show: Scheduled to vast-gpu-node-na-1

# Check service endpoints
kubectl get endpoints june-stt june-tts
# Should show: External Vast.ai IP and ports
```

## Configuration

### Environment Variables

The provider reads configuration from environment variables and Kubernetes ConfigMaps:

#### Required
- `VAST_API_KEY` - Your Vast.ai API key (from Secret)
- `NODENAME` - Virtual node name (default: `vast-gpu-node-na-1`)

#### Optional
- `VAST_PREFERRED_REGIONS` - Comma-separated regions (default: US-CA,US-TX,US-NY,US,CA)
- `VAST_MAX_LATENCY_MS` - Maximum acceptable latency (default: 50ms)
- `VAST_LATENCY_CHECK_ENABLED` - Enable latency testing (default: true)

### ConfigMap Integration

Reads selection criteria from `kube-system/vast-provider-config` and scoring weights from `kube-system/vast-selection-weights`.

## Architecture

### Components

```
┌─────────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐
│   Kubernetes API    │◄──►│  Virtual Kubelet     │◄──►│    Vast.ai API      │
│                     │    │                      │    │                     │
│ - Pod Scheduler     │    │ - Node Controller    │    │ - Instance Search   │
│ - Service Endpoints │    │ - Provider Logic     │    │ - Instance Lifecycle│
│ - Event Management  │    │ - Health Monitoring  │    │ - Status Monitoring │
└─────────────────────┘    └──────────────────────┘    └─────────────────────┘
```

### Data Flow

1. **Pod Scheduled** → Virtual node `vast-gpu-node-na-1`
2. **Provider Notified** → Receives pod creation event
3. **Instance Search** → Queries Vast.ai API with North America filters
4. **Scoring & Selection** → Chooses optimal instance (latency + cost)
5. **Instance Launch** → Creates Vast.ai instance with june-gpu-multi container
6. **Health Monitoring** → Waits for STT/TTS services to be healthy
7. **Endpoint Update** → Updates june-stt/june-tts service endpoints
8. **Status Reporting** → Reports pod as Running to Kubernetes

## Debugging

### Common Issues

#### Virtual Kubelet Not Starting
```bash
# Check pod status and events
kubectl -n kube-system describe pods -l app=virtual-kubelet-vast

# Check logs
kubectl -n kube-system logs -l app=virtual-kubelet-vast

# Verify API key
kubectl -n kube-system get secret vast-credentials -o yaml
```

#### No Instances Found
```bash
# Check selection criteria
kubectl -n kube-system get configmap vast-provider-config -o yaml

# Test API manually
curl -H "Authorization: Bearer $VAST_API_KEY" \
  'https://console.vast.ai/api/v0/bundles?rentable=true&gpu_name=RTX_3060&dph_lte=0.50&geolocation_in=US'
```

#### Pod Stuck in Pending
```bash
# Check node registration
kubectl get nodes -l provider=vast.ai

# Check pod events
kubectl describe pod -l app=june-gpu-services

# Check Virtual Kubelet logs
make dev-logs
```

#### Service Endpoints Not Updated
```bash
# Check endpoint manager logs
kubectl -n kube-system logs -l app=virtual-kubelet-vast | grep -i endpoint

# Verify RBAC permissions
kubectl describe clusterrolebinding virtual-kubelet-vast
```

### Development Commands

```bash
# Build and test locally
make build
make quick-test

# Full development cycle
make docker push deploy REGISTRY=ozzuworld

# Monitor and debug
make dev-status
make dev-debug
make dev-logs
```

## Performance

### Expected Metrics
- **Instance Selection**: 1-3 seconds (API query + scoring)
- **Instance Launch**: 30-90 seconds (Vast.ai startup time)
- **Service Health Check**: 30-60 seconds (model loading)
- **Total Deployment**: 2-4 minutes (pod create to ready)

### Geographic Performance
- **US West Coast**: 5-20ms latency, highest scoring
- **US Central**: 15-35ms latency, good performance
- **US East Coast**: 25-50ms latency, acceptable
- **Canada**: 10-40ms latency, North America bonus

## Security

- **API keys** stored in Kubernetes Secrets
- **RBAC** with minimal required permissions
- **Network isolation** via Kubernetes network policies
- **Non-root container** execution
- **Read-only filesystem** where possible

## Limitations

- **No SSH access** to instances (by design)
- **Limited log retrieval** (Vast.ai API limitation) 
- **Instance updates** require pod recreation
- **GPU sharing** within pod only (no inter-pod sharing)
- **North America focus** (other regions have lower priority)

## Contributing

1. **Test locally** with `make quick-test`
2. **Build and push** with `make push REGISTRY=your-registry`
3. **Deploy and verify** with `make deploy dev-status`
4. **Monitor logs** with `make dev-logs`

## Support

For issues with:
- **Virtual Kubelet**: Check logs and events
- **Vast.ai API**: Verify API key and instance availability
- **June services**: Check individual service health endpoints
- **Network connectivity**: Verify security groups and DNS resolution