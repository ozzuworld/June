# June Platform - Modular Installation System

This directory contains the modular installation system for the June Platform, designed to replace the monolithic `install.sh` script with focused, maintainable components.

## 📁 Directory Structure

```
scripts/
├── install-orchestrator.sh    # Main orchestrator script
├── common/                     # Shared utilities
│   ├── logging.sh             # Logging functions
│   └── validation.sh          # Validation utilities
├── install/                    # Installation phases
│   ├── 01-prerequisites.sh    # System prerequisites
│   ├── 02-docker.sh           # Docker installation
│   ├── 03-kubernetes.sh       # Kubernetes cluster
│   ├── 04-infrastructure.sh   # ingress-nginx, cert-manager
│   ├── 05-helm.sh             # Helm package manager
│   ├── 06-stunner.sh          # STUNner WebRTC gateway
│   ├── 07-livekit.sh          # LiveKit media server
│   ├── 08-june-platform.sh    # June Platform services
│   └── 09-final-setup.sh      # Final configuration
├── keycloak/                   # Keycloak utilities
├── deploy-livekit.sh           # Standalone LiveKit deployment
└── deploy-stunner-hostnet.sh   # Standalone STUNner deployment
```

## 🚀 Quick Start

### Full Installation

```bash
# Run the complete installation
sudo ./scripts/install-orchestrator.sh
```

### Partial Installation (Skip Phases)

```bash
# Skip prerequisites if already installed
sudo ./scripts/install-orchestrator.sh --skip prerequisites

# Skip multiple phases
sudo ./scripts/install-orchestrator.sh --skip prerequisites docker

# Skip by phase number or name
sudo ./scripts/install-orchestrator.sh --skip 01-prerequisites 02-docker
```

### Help

```bash
./scripts/install-orchestrator.sh --help
```

## 📋 Installation Phases

### Phase 1: Prerequisites (`01-prerequisites.sh`)
- System package updates
- Essential tools (curl, wget, git, jq, openssl)
- Basic system requirements

**Dependencies:** None  
**Duration:** ~2 minutes  
**Skip if:** System already configured

### Phase 2: Docker (`02-docker.sh`)
- Docker Engine installation
- containerd configuration for Kubernetes
- Docker daemon optimization

**Dependencies:** Prerequisites  
**Duration:** ~3 minutes  
**Skip if:** Docker already installed

### Phase 3: Kubernetes (`03-kubernetes.sh`)
- Kubernetes packages (kubelet, kubeadm, kubectl)
- Cluster initialization
- Flannel CNI installation
- Single-node configuration

**Dependencies:** Docker  
**Duration:** ~5 minutes  
**Skip if:** Kubernetes cluster already running

### Phase 4: Infrastructure (`04-infrastructure.sh`)
- ingress-nginx installation
- cert-manager installation
- Let's Encrypt ClusterIssuer
- Local storage setup

**Dependencies:** Kubernetes  
**Duration:** ~4 minutes  
**Skip if:** Infrastructure already deployed

### Phase 5: Helm (`05-helm.sh`)
- Helm 3 installation
- Common repository setup
- Repository updates

**Dependencies:** Kubernetes  
**Duration:** ~1 minute  
**Skip if:** Helm already installed

### Phase 6: STUNner (`06-stunner.sh`)
- Gateway API installation
- STUNner operator deployment
- Gateway configuration
- TURN server setup

**Dependencies:** Helm, Kubernetes  
**Duration:** ~3 minutes  
**Skip if:** WebRTC not required

### Phase 7: LiveKit (`07-livekit.sh`)
- LiveKit media server
- UDPRoute configuration
- ReferenceGrant setup

**Dependencies:** STUNner, Helm  
**Duration:** ~2 minutes  
**Skip if:** Media server not required

### Phase 8: June Platform (`08-june-platform.sh`)
- Core June services deployment
- GPU detection and AI services
- Database setup
- Identity provider (Keycloak)

**Dependencies:** All previous phases  
**Duration:** ~5-10 minutes  
**Skip if:** Only infrastructure needed

### Phase 9: Final Setup (`09-final-setup.sh`)
- System verification
- Certificate validation
- Health checks
- Final report generation

**Dependencies:** All previous phases  
**Duration:** ~1 minute  
**Skip if:** Manual verification preferred

## 🛠 Advanced Usage

### Running Individual Phases

Each phase can be run independently:

```bash
# Run a specific phase
sudo ./scripts/install/03-kubernetes.sh /path/to/june/root

# The root directory is auto-detected if not provided
sudo ./scripts/install/03-kubernetes.sh
```

### Environment Variables

Required variables (set in `config.env`):
- `DOMAIN` - Your domain name
- `LETSENCRYPT_EMAIL` - Email for SSL certificates
- `GEMINI_API_KEY` - Gemini API key for AI services
- `CLOUDFLARE_TOKEN` - Cloudflare API token for DNS challenges

Optional variables:
- `POSTGRESQL_PASSWORD` - PostgreSQL password (default: Pokemon123!)
- `KEYCLOAK_ADMIN_PASSWORD` - Keycloak admin password (default: Pokemon123!)
- `TURN_USERNAME` - TURN server username (default: june-user)
- `STUNNER_PASSWORD` - STUNner password (default: Pokemon123!)

### Debugging

Enable debug logging:
```bash
export DEBUG=true
sudo -E ./scripts/install-orchestrator.sh
```

### Log Files

Set log file for persistent logging:
```bash
export LOG_FILE=/var/log/june-install.log
sudo -E ./scripts/install-orchestrator.sh
```

## 🔧 Common Scenarios

### Fresh VM Installation
```bash
# Complete installation on a fresh Ubuntu VM
sudo ./scripts/install-orchestrator.sh
```

### Update June Platform Only
```bash
# Skip infrastructure, update June Platform
sudo ./scripts/install-orchestrator.sh --skip prerequisites docker kubernetes infrastructure helm stunner livekit
```

### Infrastructure Only
```bash
# Install Kubernetes infrastructure without June Platform
sudo ./scripts/install-orchestrator.sh --skip june-platform final-setup
```

### Development Setup
```bash
# Install everything except AI services (no GPU)
# AI services are automatically disabled if no GPU is detected
sudo ./scripts/install-orchestrator.sh
```

## 🚨 Troubleshooting

### Phase Failures

If a phase fails:
1. Check the error message
2. Review prerequisites for that phase
3. Run the phase individually with debug enabled
4. Check Kubernetes logs if applicable

### Common Issues

**Docker Installation Fails:**
```bash
# Clean up and retry
sudo systemctl stop docker containerd
sudo apt remove docker.io docker-ce docker-ce-cli containerd.io
sudo ./scripts/install/02-docker.sh
```

**Kubernetes Cluster Issues:**
```bash
# Reset cluster and retry
sudo kubeadm reset -f
sudo ./scripts/install/03-kubernetes.sh
```

**Certificate Issues:**
```bash
# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager
kubectl get certificaterequests -A
kubectl describe certificate <certificate-name> -n <namespace>
```

**STUNner Issues:**
```bash
# Check STUNner operator
kubectl logs -n stunner-system deployment/stunner
kubectl get gateway stunner-gateway -n stunner -o yaml
```

### System Requirements

**Minimum:**
- 4GB RAM
- 20GB disk space
- 2 CPU cores
- Ubuntu 20.04+ or similar Linux distribution

**Recommended:**
- 8GB RAM
- 50GB disk space
- 4 CPU cores
- GPU for AI services (optional)

### Verification Commands

```bash
# Check overall system health
kubectl get nodes
kubectl get pods --all-namespaces

# Check specific services
kubectl get pods -n june-services
kubectl get pods -n media
kubectl get gateway -n stunner

# Check certificates
kubectl get certificates -A
kubectl get clusterissuer

# Check ingress
kubectl get ingress -A
```

## 🔄 Migration from install.sh

To migrate from the old monolithic `install.sh`:

1. **Backup your current setup:**
   ```bash
   kubectl get all -A > backup-resources.yaml
   cp config.env config.env.backup
   ```

2. **Use the new modular system:**
   ```bash
   # Your existing config.env will be used automatically
   sudo ./scripts/install-orchestrator.sh
   ```

3. **Verify everything is working:**
   ```bash
   kubectl get pods -A
   # Check your services are accessible
   ```

The new system is designed to be compatible with existing installations and will detect what's already installed.

## 📚 Development

### Adding New Phases

1. Create new phase script in `scripts/install/`
2. Follow the naming convention: `XX-phase-name.sh`
3. Source common utilities:
   ```bash
   source "$(dirname "$0")/../common/logging.sh"
   source "$(dirname "$0")/../common/validation.sh"
   ```
4. Add to `PHASES` array in `install-orchestrator.sh`

### Common Utilities

Use the provided utilities for consistent behavior:
- `log()`, `success()`, `warn()`, `error()` for logging
- `verify_command()`, `wait_for_deployment()` for validation
- `header()`, `subheader()` for section formatting

## 📄 License

Same as June Platform main project.
