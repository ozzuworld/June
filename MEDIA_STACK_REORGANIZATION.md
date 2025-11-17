# Media Stack Reorganization

## Overview

The Kubernetes media stack has been reorganized into its own dedicated namespace (`media-stack`) for better separation of concerns, easier navigation, and improved maintainability.

## What Changed

### Before
```
june-services (namespace)
├── Core June platform
├── Keycloak, PostgreSQL, Redis
├── LiveKit (WebRTC)
├── Jellyfin
├── Prowlarr, Sonarr, Radarr, Lidarr
├── qBittorrent
└── Jellyseerr

stunner (namespace)
└── STUNner gateway
```

### After
```
june-services (namespace)
├── Core June platform only
├── Keycloak, PostgreSQL, Redis
└── Wildcard TLS certificates (source)

media-stack (namespace)
├── Jellyfin + all media services
├── Prowlarr, Sonarr, Radarr, Lidarr
├── qBittorrent, Jellyseerr
├── LiveKit (WebRTC)
└── Wildcard TLS certificates (synced)

stunner (namespace)
└── STUNner gateway (routes to media-stack)
```

## Directory Structure

### New Folders

```
k8s/media-stack/
├── 00-namespace.yaml           # Namespace + RBAC for cert sync
├── 01-cert-sync-cronjob.yaml   # Auto-sync certificates
└── README.md                    # Documentation

scripts/install/media-stack/
├── 00-setup-namespace.sh       # Setup namespace + cert sync
├── 01-jellyfin.sh              # Jellyfin installation
├── 02-prowlarr.sh              # Prowlarr installation
├── 03-sonarr.sh                # Sonarr installation
├── 04-radarr.sh                # Radarr installation
├── 05-lidarr.sh                # Lidarr installation
├── 06-qbittorrent.sh           # qBittorrent installation
├── 07-jellyseerr.sh            # Jellyseerr installation
└── README.md                    # Documentation

scripts/install/webrtc/
├── 01-stunner.sh               # STUNner installation
├── 02-livekit.sh               # LiveKit installation
└── README.md                    # Documentation
```

## Key Features

### 1. Certificate Synchronization

A CronJob automatically syncs wildcard TLS certificates from `june-services` to `media-stack` every 5 minutes:

```bash
# Manual trigger if needed
kubectl create job --from=cronjob/cert-sync cert-sync-manual -n june-services
```

This allows all media services to use the same `*.ozzu.world` certificate while maintaining namespace isolation.

### 2. Namespace Isolation

**Benefits:**
- Clear separation between core platform and media services
- Easier resource management and monitoring
- Better security boundaries
- Independent scaling capabilities
- Simplified troubleshooting

### 3. Organized Install Scripts

Scripts are now organized by function:
- `/media-stack/` - All media-related services
- `/webrtc/` - WebRTC components (LiveKit, STUNner)
- Flat structure still available for core platform scripts

### 4. Cross-Namespace Communication

LiveKit (in `media-stack`) communicates with STUNner (in `stunner`) via:
- **UDPRoute** - Routes UDP traffic from STUNner to LiveKit
- **ReferenceGrant** - Allows cross-namespace service references

## Installation

### Automated (Recommended)

```bash
sudo ./scripts/install-orchestrator.sh
```

The orchestrator automatically installs everything in the correct order:
1. Core infrastructure
2. WebRTC (STUNner → LiveKit)
3. Media stack namespace setup
4. All media services

### Manual

```bash
# 1. Setup media-stack namespace
sudo ./scripts/install/media-stack/00-setup-namespace.sh

# 2. Install WebRTC
sudo ./scripts/install/webrtc/01-stunner.sh
sudo ./scripts/install/webrtc/02-livekit.sh

# 3. Install media services
sudo ./scripts/install/media-stack/01-jellyfin.sh
sudo ./scripts/install/media-stack/02-prowlarr.sh
# ... etc
```

## Accessing Services

All services accessible via HTTPS with synced certificates:

- **Jellyfin**: https://tv.ozzu.world
- **Jellyseerr**: https://requests.ozzu.world
- **Sonarr**: https://sonarr.ozzu.world
- **Radarr**: https://radarr.ozzu.world
- **Lidarr**: https://lidarr.ozzu.world
- **Prowlarr**: https://prowlarr.ozzu.world
- **qBittorrent**: https://qbittorrent.ozzu.world

## Monitoring

### Check Media Stack

```bash
# All media stack pods
kubectl get pods -n media-stack

# All ingresses
kubectl get ingress -n media-stack

# Persistent volumes
kubectl get pv | grep -E "(jellyfin|prowlarr|sonarr|radarr)"

# Certificate status
kubectl get secret -n media-stack | grep wildcard-tls
```

### Check WebRTC

```bash
# LiveKit
kubectl get pods -n media-stack -l app.kubernetes.io/name=livekit-server

# STUNner
kubectl get gateway -n stunner

# UDPRoute (cross-namespace routing)
kubectl get udproute -n stunner
```

### Check Certificate Sync

```bash
# CronJob status
kubectl get cronjob cert-sync -n june-services

# Recent jobs
kubectl get jobs -n june-services | grep cert-sync

# Manual sync
kubectl create job --from=cronjob/cert-sync cert-sync-manual -n june-services
```

## Migration Notes

### Old Scripts (Deprecated)

The following old scripts are replaced by new organized versions:

| Old Script | New Script |
|------------|------------|
| `scripts/install/07-stunner.sh` | `scripts/install/webrtc/01-stunner.sh` |
| `scripts/install/08-livekit.sh` | `scripts/install/webrtc/02-livekit.sh` |
| `scripts/install/08.5-jellyfin.sh` | `scripts/install/media-stack/01-jellyfin.sh` |
| `scripts/install/08.6-prowlarr.sh` | `scripts/install/media-stack/02-prowlarr.sh` |
| `scripts/install/08.7-sonarr.sh` | `scripts/install/media-stack/03-sonarr.sh` |
| `scripts/install/08.8-radarr.sh` | `scripts/install/media-stack/04-radarr.sh` |
| `scripts/install/08.8a-lidarr.sh` | `scripts/install/media-stack/05-lidarr.sh` |
| `scripts/install/08.10-qbittorrent.sh` | `scripts/install/media-stack/06-qbittorrent.sh` |
| `scripts/install/08.9-jellyseerr.sh` | `scripts/install/media-stack/07-jellyseerr.sh` |

### Namespace Changes

- **LiveKit**: `june-services` → `media-stack`
- **All media services**: `june-services` → `media-stack`
- **STUNner**: Remains in `stunner` namespace
- **Core platform**: Remains in `june-services` namespace

## Troubleshooting

### Pods not starting

```bash
kubectl describe pod <pod-name> -n media-stack
kubectl logs <pod-name> -n media-stack
```

### Certificate issues

```bash
# Check if certificate exists in source namespace
kubectl get secret <domain>-wildcard-tls -n june-services

# Check if synced to media-stack
kubectl get secret <domain>-wildcard-tls -n media-stack

# Trigger manual sync
kubectl create job --from=cronjob/cert-sync cert-sync-manual -n june-services

# Check sync job logs
kubectl logs -n june-services job/cert-sync-xxxxx
```

### WebRTC connectivity issues

```bash
# Verify LiveKit is running
kubectl get pods -n media-stack -l app.kubernetes.io/name=livekit-server

# Check STUNner gateway
kubectl describe gateway stunner-gateway -n stunner

# Verify UDPRoute points to media-stack
kubectl describe udproute livekit-udp-route -n stunner

# Check ReferenceGrant
kubectl get referencegrant stunner-to-media-stack -n media-stack
```

## Benefits

1. **Better Organization**: Clear separation between platform and media services
2. **Easier Navigation**: Organized folder structure by function
3. **Improved Isolation**: Namespace-level separation for security and resource management
4. **Simplified Troubleshooting**: Easy to identify which namespace a service belongs to
5. **Independent Scaling**: Media stack can be scaled independently from core platform
6. **Certificate Management**: Automatic sync keeps certificates up to date

## References

- Media Stack K8s Resources: `k8s/media-stack/`
- Media Stack Install Scripts: `scripts/install/media-stack/`
- WebRTC Install Scripts: `scripts/install/webrtc/`
- Main Orchestrator: `scripts/install-orchestrator.sh`
