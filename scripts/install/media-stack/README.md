# Media Stack Installation Scripts

This directory contains installation scripts for all media stack components deployed to the `media-stack` namespace.

## Installation Order

Scripts should be run in order (orchestrator handles this automatically):

1. **00-setup-namespace.sh** - Creates namespace and certificate sync
2. **01-jellyfin.sh** - Jellyfin media server
3. **02-prowlarr.sh** - Prowlarr indexer manager
4. **03-sonarr.sh** - Sonarr TV show management
5. **04-radarr.sh** - Radarr movie management
6. **05-lidarr.sh** - Lidarr music management
7. **06-qbittorrent.sh** - qBittorrent torrent client
8. **07-jellyseerr.sh** - Jellyseerr request manager

## Common Features

All scripts:
- Use the `media-stack` namespace
- Source common logging functions from `../../common/logging.sh`
- Use standardized validation functions
- Reference the wildcard TLS certificate synced from `june-services`
- Store configs on SSD (`/mnt/ssd/media-configs/`)
- Store media on HDD (`/mnt/hdd/jellyfin-media/`)

## Running Individual Scripts

```bash
# Setup namespace first
sudo ./scripts/install/media-stack/00-setup-namespace.sh

# Install Jellyfin
sudo ./scripts/install/media-stack/01-jellyfin.sh

# Install other components as needed
sudo ./scripts/install/media-stack/02-prowlarr.sh
```

## Storage Layout

### SSD Storage (/mnt/ssd/)
- `jellyfin-config/` - Jellyfin configuration and database
- `media-configs/prowlarr/` - Prowlarr configuration
- `media-configs/sonarr/` - Sonarr configuration
- `media-configs/radarr/` - Radarr configuration
- `media-configs/lidarr/` - Lidarr configuration
- `media-configs/qbittorrent/` - qBittorrent configuration
- `media-configs/jellyseerr/` - Jellyseerr configuration

### HDD Storage (/mnt/hdd/jellyfin-media/)
- `movies/` - Movie files (managed by Radarr)
- `tv/` - TV show files (managed by Sonarr)
- `music/` - Music files (managed by Lidarr)
- `downloads/complete/` - Completed downloads
- `downloads/incomplete/` - In-progress downloads

## Namespace Isolation

The media stack is isolated in its own namespace:

**Benefits:**
- Cleaner organization
- Easier resource management
- Better security boundaries
- Independent scaling
- Simplified troubleshooting

**Certificate Handling:**
- Certificates are automatically synced from `june-services` namespace
- A CronJob runs every 5 minutes to keep certificates up to date
- All ingresses use the same `*.ozzu.world` wildcard certificate

## Environment Variables

Scripts read from `config.env`:
- `DOMAIN` - Base domain (e.g., ozzu.world)
- `MEDIA_STACK_USERNAME` - Default admin username
- `MEDIA_STACK_PASSWORD` - Default admin password
- Other configuration as needed

## Verification

After installation, verify:

```bash
# Check all pods are running
kubectl get pods -n media-stack

# Check ingresses are created
kubectl get ingress -n media-stack

# Check persistent volumes
kubectl get pv | grep -E "(jellyfin|prowlarr|sonarr|radarr|lidarr|qbittorrent|jellyseerr)"

# Check persistent volume claims
kubectl get pvc -n media-stack

# Verify certificate sync
kubectl get secret -n media-stack | grep wildcard-tls
```

## Troubleshooting

### Pod not starting
```bash
# Check pod status
kubectl describe pod <pod-name> -n media-stack

# Check logs
kubectl logs <pod-name> -n media-stack
```

### Storage issues
```bash
# Check PV status
kubectl get pv

# Check PVC status
kubectl get pvc -n media-stack

# Verify directory permissions on host
ls -la /mnt/ssd/
ls -la /mnt/hdd/jellyfin-media/
```

### Ingress/certificate issues
```bash
# Check ingress
kubectl describe ingress <ingress-name> -n media-stack

# Verify certificate exists
kubectl get secret <domain>-wildcard-tls -n media-stack

# Check certificate sync job
kubectl get cronjob cert-sync -n june-services
```
