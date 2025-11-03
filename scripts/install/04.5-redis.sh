@@ -0,0 +1,38 @@
#!/bin/bash
# June Platform - Phase 4.5: Redis Deployment
# Deploy Redis using Bitnami Helm chart into june-services namespace

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

# Source configuration
CONFIG_FILE="${ROOT_DIR}/config.env"
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
fi

install_redis() {
    log "Installing Redis Helm chart..."

    # Add Bitnami repo if not already present
    if ! helm repo list | grep -q bitnami; then
        helm repo add bitnami https://charts.bitnami.com/bitnami
        helm repo update
    fi

    # Install or upgrade Redis
    helm upgrade --install june-redis bitnami/redis \
        --namespace june-services --create-namespace \
        --set auth.password="${REDIS_PASSWORD:-defaultpassword}" \
        --set persistence.enabled=true \
        --set persistence.size=8Gi \
        --timeout 10m

    success "Redis installed or upgraded"
}

install_redis