#!/bin/bash
#
# June Dark OSINT Framework - MACHINE 2 Installation Script
# Ubuntu 22.04 LTS
# Run as: sudo ./install-node2.sh
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
log_step() { echo -e "\n${BLUE}[STEP]${NC} $1\n"; }

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   log_error "This script must be run as root (use sudo)"
fi

INSTALL_DIR="/opt/june-dark"
DATA_DIR="/data/june-dark"
BACKUP_DIR="/data/june-dark/backups"

log_step "1/10 - System Updates and Prerequisites"
apt-get update
apt-get upgrade -y
apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    software-properties-common \
    git \
    htop \
    iotop \
    net-tools \
    jq \
    python3-pip \
    python3-venv

log_step "2/10 - Setting up Storage Structure"
# Create directory structure on 900GB HDD
mkdir -p ${DATA_DIR}/{docker-volumes,minio-data,elasticsearch,neo4j,postgres,redis,rabbitmq,artifacts,logs,backups}
mkdir -p ${DATA_DIR}/docker-volumes/{es-data,kibana-data,neo4j-data,neo4j-logs,pg-data,redis-data,rabbit-data,minio-data,artifacts,faiss-index,logs}

log_info "Data directory: ${DATA_DIR}"
log_info "Available space: $(df -h ${DATA_DIR} | tail -1 | awk '{print $4}')"

log_step "3/10 - Installing Docker Engine"
# Remove old versions
apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Add Docker's official GPG key
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start and enable Docker
systemctl start docker
systemctl enable docker

log_info "Docker version: $(docker --version)"
log_info "Docker Compose version: $(docker compose version)"

log_step "4/10 - Configuring Docker for Production"
# Configure Docker daemon for better performance and logging
cat > /etc/docker/daemon.json <<EOF
{
  "data-root": "${DATA_DIR}/docker-volumes",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "default-address-pools": [
    {
      "base": "172.17.0.0/16",
      "size": 24
    }
  ],
  "storage-driver": "overlay2",
  "live-restore": true,
  "userland-proxy": false
}
EOF

systemctl restart docker
log_info "Docker configured with data-root: ${DATA_DIR}/docker-volumes"

log_step "5/10 - Setting up Kernel Parameters for Elasticsearch"
# Increase vm.max_map_count for Elasticsearch
echo "vm.max_map_count=262144" >> /etc/sysctl.conf
echo "vm.swappiness=1" >> /etc/sysctl.conf
echo "net.core.somaxconn=65535" >> /etc/sysctl.conf
sysctl -p

# Set file descriptor limits
cat >> /etc/security/limits.conf <<EOF
* soft nofile 65536
* hard nofile 65536
* soft nproc 32768
* hard nproc 32768
EOF

log_step "6/10 - Network Configuration"
# Allow required ports on firewall (if UFW is active)
if command -v ufw &> /dev/null && ufw status | grep -q "Status: active"; then
    log_info "Configuring UFW firewall..."
    
    # Internal network (MACHINE 1 communication)
    ufw allow from 10.0.0.0/24 to any port 9200 comment "Elasticsearch"
    ufw allow from 10.0.0.0/24 to any port 5601 comment "Kibana"
    ufw allow from 10.0.0.0/24 to any port 7474 comment "Neo4j Browser"
    ufw allow from 10.0.0.0/24 to any port 7687 comment "Neo4j Bolt"
    ufw allow from 10.0.0.0/24 to any port 5432 comment "PostgreSQL"
    ufw allow from 10.0.0.0/24 to any port 6379 comment "Redis"
    ufw allow from 10.0.0.0/24 to any port 5672 comment "RabbitMQ"
    ufw allow from 10.0.0.0/24 to any port 15672 comment "RabbitMQ Management"
    ufw allow from 10.0.0.0/24 to any port 9000 comment "MinIO API"
    ufw allow from 10.0.0.0/24 to any port 9001 comment "MinIO Console"
    ufw allow from 10.0.0.0/24 to any port 8080 comment "Orchestrator API"
    
    ufw reload
    log_info "Firewall rules configured"
else
    log_warn "UFW not active. Configure firewall rules manually if needed."
fi

log_step "7/10 - Creating June Dark Directory Structure"
mkdir -p ${INSTALL_DIR}/{services,configs,scripts,logs}

# Create directory structure for services
mkdir -p ${INSTALL_DIR}/services/{orchestrator,collector,enricher,ops-ui}
mkdir -p ${INSTALL_DIR}/services/orchestrator/{app,app/api,app/models,app/utils}
mkdir -p ${INSTALL_DIR}/services/collector/{app,app/spiders,app/utils}
mkdir -p ${INSTALL_DIR}/services/enricher/{app,app/processors,app/utils}
mkdir -p ${INSTALL_DIR}/configs/{elasticsearch,neo4j,kibana}

log_step "8/10 - Installing Python Tools (for management scripts)"
apt-get install -y python3-docker python3-httpx python3-requests


log_step "9/10 - Creating Management Aliases"
cat >> /root/.bashrc <<'EOF'

# June Dark OSINT Aliases
alias june-logs='cd /opt/june-dark && docker compose logs -f'
alias june-status='cd /opt/june-dark && docker compose ps'
alias june-restart='cd /opt/june-dark && docker compose restart'
alias june-stop='cd /opt/june-dark && docker compose stop'
alias june-start='cd /opt/june-dark && docker compose up -d'
alias june-health='curl -s http://localhost:8080/health | jq'
alias june-stats='docker stats --no-stream'
EOF

log_step "10/10 - Setting Permissions"
chown -R root:root ${INSTALL_DIR}
chmod -R 755 ${INSTALL_DIR}

# Set proper permissions for data directory
chmod -R 755 ${DATA_DIR}

log_info "
${GREEN}═══════════════════════════════════════════════════════════${NC}
${GREEN}  June Dark OSINT Framework - Node 2 Installation Complete ${NC}
${GREEN}═══════════════════════════════════════════════════════════${NC}

Installation Directory: ${INSTALL_DIR}
Data Directory: ${DATA_DIR}
Available Space: $(df -h ${DATA_DIR} | tail -1 | awk '{print $4}')

Next Steps:
1. Copy the docker-compose.yml to ${INSTALL_DIR}/
2. Copy the .env file to ${INSTALL_DIR}/
3. Copy service code to ${INSTALL_DIR}/services/
4. Run: cd ${INSTALL_DIR} && docker compose up -d

Useful Commands:
  june-status   - Check service status
  june-logs     - View live logs
  june-health   - Check API health
  june-stats    - View resource usage

Documentation: https://github.com/ozzuworld/june
"