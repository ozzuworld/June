# GPU Services with SkyPilot

## Architecture
```
┌─────────────────────────────────────┐
│   Kubernetes Cluster (Orchestration)│
│                                     │
│  ┌───────────────┐  ┌─────────────┐│
│  │ orchestrator  │  │  livekit    ││
│  └───────────────┘  └─────────────┘│
└─────────────────────────────────────┘
           ↑ Headscale VPN
           │
┌─────────────────────────────────────┐
│  SkyPilot (Local CLI or K8s Pod)    │
│  - GPU provisioning                 │
│  - Cost optimization                │
│  - Lifecycle management             │
└─────────────────────────────────────┘
           ↓ Vast.ai API
┌─────────────────────────────────────┐
│  Vast.ai Marketplace                │
│  ┌─────────────────────────────────┐│
│  │ GPU Instance (Docker)           ││
│  │  ├─ june-tts (port 8000)        ││
│  │  └─ june-stt (port 8001)        ││
│  │  + Tailscale (VPN to K8s)      ││
│  └─────────────────────────────────┘│
└─────────────────────────────────────┘
```

## Quick Start
```bash
# Deploy GPU services
./scripts/skypilot/deploy-gpu-services.sh

# Monitor deployment
sky status --all
sky logs june-gpu-services -f
```

## Management Commands
```bash
# Status
sky status june-gpu-services

# Logs
sky logs june-gpu-services --follow

# SSH access
sky ssh june-gpu-services

# Execute commands
sky exec june-gpu-services "docker ps"
sky exec june-gpu-services "nvidia-smi"

# Restart services
sky exec june-gpu-services "docker-compose restart"

# Stop (keeps data)
sky stop june-gpu-services

# Start
sky start june-gpu-services

# Terminate (deletes instance)
sky down june-gpu-services
```

## Cost Management
```bash
# View current costs
sky cost-report

# Set budget limits
sky launch --max-price 0.30 june-gpu-services.yaml

# Auto-stop after idle
sky launch --down-after-idle 30m june-gpu-services.yaml
```

## Troubleshooting

### Service not connecting to orchestrator
```bash
# Check Tailscale status
sky ssh june-gpu-services
tailscale status
ping june-orchestrator  # Should work via Headscale

# Check service logs
docker logs june-tts
docker logs june-stt
```

### High costs
```bash
# Check hourly rate
sky status --all | grep "$/hr"

# Switch to cheaper GPU
sky launch --gpus RTX3060:1 june-gpu-services.yaml

# Stop when not in use
sky stop june-gpu-services
```