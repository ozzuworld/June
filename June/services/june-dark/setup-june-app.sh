#!/bin/bash

# June Dark OSINT Framework - Application Setup Script
# Run after install-node2.sh to deploy the application services

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

INSTALL_DIR="/opt/june-dark"
TEMP_DIR="/tmp/june-setup"
REPO_URL="https://github.com/ozzuworld/June.git"

log_step "1/6 - Downloading Complete Application Code"

# Clean up any previous temp directory
rm -rf ${TEMP_DIR}

# Clone the repository with all files
log_info "Cloning June repository..."
git clone --recursive ${REPO_URL} ${TEMP_DIR}

log_step "2/6 - Copying Service Files"

# Copy services with proper structure
log_info "Copying application services..."
cp -r ${TEMP_DIR}/June/services/june-dark/services/* ${INSTALL_DIR}/services/

# Copy configuration files
log_info "Copying configuration files..."
mkdir -p ${INSTALL_DIR}/configs
cp -r ${TEMP_DIR}/June/services/june-dark/configs/* ${INSTALL_DIR}/configs/ 2>/dev/null || true

# Copy main application files
cp ${TEMP_DIR}/June/services/june-dark/docker-compose.yml ${INSTALL_DIR}/
cp ${TEMP_DIR}/June/services/june-dark/.env ${INSTALL_DIR}/
cp ${TEMP_DIR}/June/services/june-dark/deploy.sh ${INSTALL_DIR}/
chmod +x ${INSTALL_DIR}/deploy.sh

log_step "3/6 - Verifying Service Structure"

# Verify all required Dockerfiles exist
SERVICES=("orchestrator" "collector" "enricher" "ops-ui")
for service in "${SERVICES[@]}"; do
    if [ -f "${INSTALL_DIR}/services/${service}/Dockerfile" ]; then
        log_info "✅ ${service}/Dockerfile found"
    else
        log_error "❌ ${service}/Dockerfile missing"
    fi
done

log_step "4/6 - Creating Volume Directories"

# Create all required volume mount points
mkdir -p /data/june-dark/docker-volumes/{es-data,kibana-data,neo4j-data,neo4j-logs,pg-data,redis-data,rabbit-data,minio-data,artifacts,logs}
chown -R root:root /data/june-dark/docker-volumes/
chmod -R 755 /data/june-dark/docker-volumes/

log_step "5/6 - Fixing Docker Compose Configuration"

cd ${INSTALL_DIR}

# Remove obsolete version line
sed -i '/^version:/d' docker-compose.yml

# Set proper environment file
if [ ! -f ".env" ]; then
    log_warn "Creating default .env file"
    cp ${TEMP_DIR}/June/services/june-dark/.env .env
fi

log_step "6/6 - Starting June Dark OSINT Framework"

# Stop any existing containers
docker compose down --remove-orphans 2>/dev/null || true

# Start infrastructure services first
log_info "Starting infrastructure services..."
docker compose up -d elasticsearch redis postgres neo4j rabbitmq minio kibana

# Wait for services to be ready
log_info "Waiting for infrastructure services to start..."
sleep 30

# Start application services
log_info "Starting application services..."
docker compose up -d orchestrator collector enricher ops-ui

# Clean up temp directory
rm -rf ${TEMP_DIR}

log_step "Deployment Complete!"

log_info "
${GREEN}═══════════════════════════════════════════════════════════${NC}
${GREEN}  June Dark OSINT Framework - Application Setup Complete   ${NC}
${GREEN}═══════════════════════════════════════════════════════════${NC}

Services Status:
$(docker compose ps)

Useful Commands:
  cd ${INSTALL_DIR}
  docker compose ps          # Check status
  docker compose logs -f     # View logs
  docker compose restart     # Restart all
  ./deploy.sh status         # Detailed status

Access Points:
  - API: http://localhost:8080
  - Kibana: http://localhost:5601
  - Neo4j: http://localhost:7474
  - RabbitMQ: http://localhost:15672
  - MinIO: http://localhost:9001
  - Ops UI: http://localhost:8090
"
