# Vast.ai split deployment for june-stt and june-tts

This guide deploys STT and TTS as separate containers on a single Vast.ai GPU instance using prebuilt images, each connected to Headscale via container-level Tailscale.

## Prerequisites
- Docker + Docker Compose installed on the Vast.ai instance
- A reusable Headscale preauth key
- Open ports 8000 (TTS) and 8001 (STT) on the host if you want local access

## Files
- deployments/vast/june-gpu-stack.compose.yml — Compose stack for STT/TTS
- scripts/deploy-vast-gpu-stack.sh — Helper script to deploy and run health checks

## Quick start

```bash
cd /path/to/June
./scripts/deploy-vast-gpu-stack.sh
# Edit .env to set TAILSCALE_AUTH_KEY
./scripts/deploy-vast-gpu-stack.sh
```

The script will:
- Create a .env file (once) with:
  - TAILSCALE_AUTH_KEY (required for Headscale)
  - TTS_PORT (default 8000), STT_PORT (default 8001)
- Bring up the stack with docker compose
- Check container status and service health
- Show Tailscale status inside each container if available

## Compose services
- june-tts: ghcr.io/ozzuworld/june-tts:latest (exposes 8000)
- june-stt: ghcr.io/ozzuworld/june-stt:latest (exposes 8001)

Both containers set runtime env to avoid numba/librosa caching issues:
- NUMBA_DISABLE_JIT=1
- NUMBA_CACHE_DIR=/tmp/numba_cache
- PYTORCH_JIT=0 (TTS)

## Health checks
```bash
curl -f http://localhost:8000/healthz   # TTS
curl -f http://localhost:8001/healthz   # STT
```

## Headscale/Tailscale
- Generate a reusable key on your Headscale instance:
```bash
kubectl exec -n headscale <pod> -- headscale preauthkeys create \
  --user ozzu \
  --expiration 168h \
  --reusable
```
- Set TAILSCALE_AUTH_KEY in .env with the value returned above.

## Notes
- The previous single-container june-gpu-multi approach is deprecated for stability reasons (dependency coupling). This split deployment mirrors the working standalone images without dependency conflicts.
- If you prefer host-level Tailscale, remove TAILSCALE_AUTH_KEY and run tailscale on the host; containers can then reach K8s services via host routing.
