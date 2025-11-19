#!/bin/bash
# June Platform - Complete Observability Stack Installation
# Installs Prometheus, Grafana, Loki, AlertManager, and all exporters

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Load configuration
if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
else
    error "config.env not found. Please create it from config.env.example"
fi

[ -z "$DOMAIN" ] && error "DOMAIN variable is not set in config.env"

NAMESPACE="monitoring"
MONITORING_DIR="${ROOT_DIR}/k8s/monitoring"

echo "================================================================"
echo "June Platform - Observability Stack Installation"
echo "================================================================"
echo ""
echo "This will install:"
echo "  📊 Prometheus (metrics collection)"
echo "  📈 Grafana (visualization)"
echo "  📝 Loki + Promtail (log aggregation)"
echo "  🚨 AlertManager (alerting)"
echo "  📟 Database Exporters (PostgreSQL, Redis, RabbitMQ, Elasticsearch)"
echo ""
echo "Domain: $DOMAIN"
echo "Namespace: $NAMESPACE"
echo ""

# Ask for confirmation
read -p "Continue with installation? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    error "Installation cancelled"
fi

# Check if helm is installed
if ! command -v helm &> /dev/null; then
    error "Helm is not installed. Please install Helm first: https://helm.sh/docs/intro/install/"
fi

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    error "kubectl is not installed. Please install kubectl first"
fi

# Check if cluster is accessible
if ! kubectl cluster-info &> /dev/null; then
    error "Cannot connect to Kubernetes cluster. Please check your kubeconfig"
fi

echo ""
log "Starting installation..."
echo ""

## PHASE 1: Add Helm repositories
log "Phase 1/6: Adding Helm repositories..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo add grafana https://grafana.github.io/helm-charts 2>/dev/null || true
helm repo update
success "Helm repositories added"
echo ""

## PHASE 2: Create namespace
log "Phase 2/6: Creating monitoring namespace..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
success "Namespace $NAMESPACE ready"
echo ""

## PHASE 3: Prepare Helm values (replace domain placeholder)
log "Phase 3/6: Preparing configuration files..."
TEMP_DIR="/tmp/june-monitoring-$$"
mkdir -p "$TEMP_DIR"

# Copy and update Prometheus values
sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" "${MONITORING_DIR}/prometheus/values.yaml" > "${TEMP_DIR}/prometheus-values.yaml"

# Copy Loki values
cp "${MONITORING_DIR}/loki/values.yaml" "${TEMP_DIR}/loki-values.yaml"

success "Configuration files prepared"
echo ""

## PHASE 4: Install kube-prometheus-stack
log "Phase 4/6: Installing kube-prometheus-stack (Prometheus + Grafana + AlertManager)..."
log "This may take 5-10 minutes..."

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace "$NAMESPACE" \
  --values "${TEMP_DIR}/prometheus-values.yaml" \
  --wait \
  --timeout 15m

success "kube-prometheus-stack installed"
echo ""

# Wait for Prometheus to be ready
log "Waiting for Prometheus to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=prometheus \
  -n "$NAMESPACE" \
  --timeout=300s || warn "Prometheus pod not ready yet, but continuing..."

success "Prometheus is ready"
echo ""

## PHASE 5: Install Loki stack
log "Phase 5/6: Installing Loki stack (Log aggregation)..."
log "This may take 3-5 minutes..."

helm upgrade --install loki grafana/loki-stack \
  --namespace "$NAMESPACE" \
  --values "${TEMP_DIR}/loki-values.yaml" \
  --wait \
  --timeout 10m

success "Loki stack installed"
echo ""

# Wait for Loki to be ready
log "Waiting for Loki to be ready..."
kubectl wait --for=condition=ready pod \
  -l app=loki \
  -n "$NAMESPACE" \
  --timeout=300s || warn "Loki pod not ready yet, but continuing..."

success "Loki is ready"
echo ""

## PHASE 6: Deploy exporters and ServiceMonitors
log "Phase 6/6: Deploying database exporters and ServiceMonitors..."

# Deploy PostgreSQL exporters
log "Deploying PostgreSQL exporters..."
kubectl apply -f "${MONITORING_DIR}/exporters/postgres-exporter-june-services.yaml"
kubectl apply -f "${MONITORING_DIR}/exporters/postgres-exporter-june-dark.yaml"

# Deploy Redis exporter
log "Deploying Redis exporter..."
kubectl apply -f "${MONITORING_DIR}/exporters/redis-exporter.yaml"

# Deploy RabbitMQ exporter
log "Deploying RabbitMQ exporter..."
kubectl apply -f "${MONITORING_DIR}/exporters/rabbitmq-exporter.yaml"

# Deploy Elasticsearch exporter
log "Deploying Elasticsearch exporter..."
kubectl apply -f "${MONITORING_DIR}/exporters/elasticsearch-exporter.yaml"

# Deploy ServiceMonitor for june-orchestrator
log "Deploying ServiceMonitor for june-orchestrator..."
kubectl apply -f "${MONITORING_DIR}/servicemonitors/june-orchestrator.yaml"

# Deploy custom alert rules
log "Deploying custom alert rules..."
kubectl apply -f "${MONITORING_DIR}/alerts/june-platform-alerts.yaml"

success "All exporters and ServiceMonitors deployed"
echo ""

# Wait for exporters to be ready
log "Waiting for exporters to be ready..."
sleep 10

# Cleanup temp files
rm -rf "$TEMP_DIR"

echo ""
echo "================================================================"
echo "✅ Observability Stack Installation Complete!"
echo "================================================================"
echo ""
echo "📊 Prometheus: https://prometheus.${DOMAIN}"
echo "📈 Grafana:    https://grafana.${DOMAIN}"
echo "🚨 AlertManager: https://alertmanager.${DOMAIN}"
echo ""
echo "🔑 Grafana Credentials:"
echo "  Username: admin"
echo "  Password: Run this command to get password:"
echo "    kubectl get secret -n monitoring kube-prometheus-stack-grafana \\"
echo "      -o jsonpath=\"{.data.admin-password}\" | base64 --decode; echo"
echo ""
echo "📋 Quick Access Commands:"
echo ""
echo "# Port-forward Grafana (if ingress not working):"
echo "kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80"
echo ""
echo "# Port-forward Prometheus:"
echo "kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090"
echo ""
echo "# View Prometheus targets:"
echo "kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090"
echo "Open: http://localhost:9090/targets"
echo ""
echo "# Check ServiceMonitors:"
echo "kubectl get servicemonitors -A"
echo ""
echo "# Check Prometheus rules:"
echo "kubectl get prometheusrules -n monitoring"
echo ""
echo "# View all monitoring pods:"
echo "kubectl get pods -n monitoring"
echo ""
echo "================================================================"
echo ""
echo "📚 Next Steps:"
echo ""
echo "1. Access Grafana and login with admin credentials"
echo "2. Verify all datasources are connected (Prometheus, Loki)"
echo "3. Import pre-built dashboards from Grafana.com:"
echo "   - PostgreSQL: 9628"
echo "   - Redis: 11835"
echo "   - RabbitMQ: 10991"
echo "   - Elasticsearch: 14191"
echo "4. Configure AlertManager notifications (Slack/Email)"
echo "   Edit: k8s/monitoring/prometheus/values.yaml (alertmanager.config)"
echo "5. Create custom dashboards for June Platform services"
echo ""
echo "📖 Documentation: docs/OBSERVABILITY-STACK-DESIGN.md"
echo ""
echo "================================================================"
echo ""

success "Installation completed successfully!"
echo ""
echo "⚠️  IMPORTANT: Change the Grafana admin password immediately!"
echo "   Go to: https://grafana.${DOMAIN}/profile/password"
echo ""
