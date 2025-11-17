# Media Stack Namespace

This directory contains Kubernetes resources for the `media-stack` namespace, which houses all media-related services and WebRTC components.

## Architecture

The media stack has been separated from `june-services` into its own dedicated namespace for better organization and isolation:

```
june-services (namespace)
  ├── Core June platform services
  ├── Keycloak (SSO provider)
  ├── PostgreSQL
  └── Wildcard TLS certificates (source)

media-stack (namespace)
  ├── Jellyfin (media server)
  ├── Prowlarr (indexer manager)
  ├── Sonarr (TV shows)
  ├── Radarr (movies)
  ├── Lidarr (music)
  ├── qBittorrent (downloader)
  ├── Jellyseerr (request manager)
  ├── LiveKit (WebRTC server)
  └── Wildcard TLS certificates (synced from june-services)

stunner (namespace)
  └── STUNner Gateway (TURN server routing to LiveKit)
```

## Components

### 00-namespace.yaml
- Creates `media-stack` namespace
- Sets up RBAC for certificate copying between namespaces
- Includes ServiceAccount and Role/RoleBinding for cert-copier

### 01-cert-sync-cronjob.yaml
- CronJob that syncs wildcard TLS certificates from `june-services` to `media-stack`
- Runs every 5 minutes to keep certificates in sync
- Ensures all media stack services can use `*.ozzu.world` certificates

## Certificate Synchronization

The media stack uses the same wildcard certificate as the main June platform (`*.ozzu.world`), but since it's in a separate namespace, we need to copy the certificate.

**How it works:**
1. cert-manager creates certificates in `june-services` namespace
2. A CronJob (`cert-sync`) copies the wildcard certificate to `media-stack` every 5 minutes
3. All media stack ingresses reference the synced certificate

**Manual sync (if needed):**
```bash
# Trigger an immediate certificate sync
kubectl create job --from=cronjob/cert-sync cert-sync-manual -n june-services
```

## Installation

The media stack is installed via the main orchestrator script with the following phases:

```bash
# Install all components
sudo ./scripts/install-orchestrator.sh

# Or install specific media stack components
sudo ./scripts/install/media-stack/00-setup-namespace.sh
sudo ./scripts/install/media-stack/01-jellyfin.sh
sudo ./scripts/install/media-stack/02-prowlarr.sh
# ... etc
```

## Accessing Services

All services are accessible via HTTPS using the synced wildcard certificate:

- **Jellyfin**: https://tv.ozzu.world
- **Jellyseerr**: https://requests.ozzu.world
- **Sonarr**: https://sonarr.ozzu.world
- **Radarr**: https://radarr.ozzu.world
- **Lidarr**: https://lidarr.ozzu.world
- **Prowlarr**: https://prowlarr.ozzu.world
- **qBittorrent**: https://qbittorrent.ozzu.world

## Storage

Media stack uses optimized storage:
- **Config files**: `/mnt/ssd/` (fast-ssd storage class)
- **Media files**: `/mnt/hdd/jellyfin-media/` (slow-hdd storage class)

## Monitoring

Check media stack status:
```bash
# View all media stack pods
kubectl get pods -n media-stack

# View ingresses
kubectl get ingress -n media-stack

# Check certificate sync status
kubectl get cronjob cert-sync -n june-services
kubectl get job -n june-services | grep cert-sync

# Verify certificate exists
kubectl get secret -n media-stack | grep wildcard-tls
```

## WebRTC Integration

LiveKit (WebRTC server) runs in the `media-stack` namespace and connects to STUNner (in `stunner` namespace) for TURN relay:

- **LiveKit**: `livekit-livekit-server.media-stack.svc.cluster.local`
- **STUNner**: Handles UDP routing to LiveKit via UDPRoute

A ReferenceGrant allows cross-namespace access from `stunner` to `media-stack`.

## Troubleshooting

### Certificate not syncing
```bash
# Check CronJob
kubectl get cronjob cert-sync -n june-services

# View recent sync jobs
kubectl get jobs -n june-services | grep cert-sync

# Check logs
kubectl logs -n june-services job/cert-sync-xxxxx
```

### Service not accessible
```bash
# Check pod status
kubectl get pods -n media-stack

# Check ingress
kubectl get ingress -n media-stack

# Verify certificate exists
kubectl get secret <domain>-wildcard-tls -n media-stack
```

### LiveKit WebRTC issues
```bash
# Check LiveKit pod
kubectl get pods -n media-stack -l app.kubernetes.io/name=livekit-server

# Check STUNner gateway
kubectl get gateway -n stunner

# Check UDPRoute
kubectl get udproute -n stunner

# Check ReferenceGrant
kubectl get referencegrant -n media-stack
```
