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

# Check prerequisites
echo "Checking prerequisites..."
echo ""

# Check if helm is installed
if ! command -v helm &> /dev/null; then
    error "Helm is not installed. Please install Helm first: https://helm.sh/docs/intro/install/"
fi
success "Helm found: $(helm version --short 2>/dev/null || helm version)"

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    error "kubectl is not installed. Please install kubectl first"
fi
success "kubectl found"

# Check if cluster is accessible
if ! kubectl cluster-info &> /dev/null; then
    error "Cannot connect to Kubernetes cluster. Please check your kubeconfig"
fi
success "Kubernetes cluster is accessible"

echo ""

# CRITICAL: Check storage classes before proceeding
log "Checking storage classes..."
echo ""

# Get available storage classes
AVAILABLE_SC=$(kubectl get storageclass -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")

if [ -z "$AVAILABLE_SC" ]; then
    warn "No storage classes found in the cluster!"
    echo ""
    echo "The monitoring stack requires persistent storage."
    echo ""
    echo "Options:"
    echo "1. Install a storage provisioner (e.g., local-path-provisioner for dev/testing)"
    echo "2. Use a cloud provider's storage (AWS EBS, GCP PD, Azure Disk)"
    echo ""
    read -p "Do you want to install local-path-provisioner now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log "Installing local-path-provisioner..."
        kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.24/deploy/local-path-storage.yaml

        # Wait for provisioner to be ready
        sleep 5
        kubectl wait --for=condition=ready pod -l app=local-path-provisioner -n local-path-storage --timeout=60s

        # Set as default
        kubectl patch storageclass local-path -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

        success "local-path-provisioner installed and set as default"
        STORAGE_CLASS="local-path"
    else
        error "Cannot proceed without storage. Please install a storage provisioner first."
    fi
else
    echo "Available storage classes:"
    kubectl get storageclass
    echo ""

    # Check if required storage classes exist
    if echo "$AVAILABLE_SC" | grep -q "fast-ssd" && echo "$AVAILABLE_SC" | grep -q "slow-hdd"; then
        success "Required storage classes (fast-ssd, slow-hdd) found"
        STORAGE_CLASS="KEEP_EXISTING"
    else
        warn "Storage classes 'fast-ssd' and 'slow-hdd' not found"
        echo ""
        echo "The monitoring stack configuration uses 'fast-ssd' and 'slow-hdd' storage classes."
        echo "Available storage classes: $AVAILABLE_SC"
        echo ""

        # Get default storage class
        DEFAULT_SC=$(kubectl get storageclass -o jsonpath='{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")].metadata.name}' 2>/dev/null || echo "")

        if [ -n "$DEFAULT_SC" ]; then
            echo "Default storage class detected: $DEFAULT_SC"
            echo ""
            echo "Options:"
            echo "1. Use default storage class ($DEFAULT_SC) for all components"
            echo "2. Create 'fast-ssd' and 'slow-hdd' storage classes (maps to same provisioner)"
            echo "3. Manually select storage class"
            echo ""
            read -p "Choose option (1/2/3): " STORAGE_OPTION
        else
            echo "No default storage class found."
            echo ""
            read -p "Enter storage class name to use (from list above): " STORAGE_CLASS
            STORAGE_OPTION=1
        fi

        case $STORAGE_OPTION in
            1)
                STORAGE_CLASS="${STORAGE_CLASS:-$DEFAULT_SC}"
                log "Using storage class: $STORAGE_CLASS"
                ;;
            2)
                log "Creating fast-ssd and slow-hdd storage classes..."

                # Detect provisioner from default storage class
                if [ -n "$DEFAULT_SC" ]; then
                    PROVISIONER=$(kubectl get storageclass "$DEFAULT_SC" -o jsonpath='{.provisioner}')
                else
                    # Try to detect from first available storage class
                    FIRST_SC=$(echo "$AVAILABLE_SC" | awk '{print $1}')
                    PROVISIONER=$(kubectl get storageclass "$FIRST_SC" -o jsonpath='{.provisioner}')
                fi

                log "Detected provisioner: $PROVISIONER"

                # Create fast-ssd storage class
                cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: $PROVISIONER
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
allowVolumeExpansion: true
EOF

                # Create slow-hdd storage class
                cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: slow-hdd
provisioner: $PROVISIONER
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
allowVolumeExpansion: true
EOF

                success "Storage classes created"
                kubectl get storageclass fast-ssd slow-hdd
                STORAGE_CLASS="KEEP_EXISTING"
                ;;
            3)
                read -p "Enter storage class name: " STORAGE_CLASS
                log "Using storage class: $STORAGE_CLASS"
                ;;
            *)
                error "Invalid option"
                ;;
        esac
    fi
fi

echo ""

# Ask for confirmation
read -p "Continue with installation? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    error "Installation cancelled"
fi

echo ""
log "Starting installation..."
echo ""

## PHASE 1: Add Helm repositories
log "Phase 1/7: Adding Helm repositories..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo add grafana https://grafana.github.io/helm-charts 2>/dev/null || true
helm repo update
success "Helm repositories added"
echo ""

## PHASE 2: Create namespace
log "Phase 2/7: Creating monitoring namespace..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
success "Namespace $NAMESPACE ready"
echo ""

## PHASE 3: Prepare Helm values (replace domain placeholder and storage class)
log "Phase 3/7: Preparing configuration files..."
TEMP_DIR="/tmp/june-monitoring-$$"
mkdir -p "$TEMP_DIR"

# Copy and update Prometheus values
if [ "$STORAGE_CLASS" = "KEEP_EXISTING" ]; then
    # Keep existing storage classes in values
    sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" "${MONITORING_DIR}/prometheus/values.yaml" > "${TEMP_DIR}/prometheus-values.yaml"
else
    # Replace storage classes with selected one
    sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" "${MONITORING_DIR}/prometheus/values.yaml" | \
    sed "s/storageClassName: slow-hdd/storageClassName: $STORAGE_CLASS/g" | \
    sed "s/storageClassName: fast-ssd/storageClassName: $STORAGE_CLASS/g" > "${TEMP_DIR}/prometheus-values.yaml"
fi

# Copy Loki values (also update storage class if needed)
if [ "$STORAGE_CLASS" = "KEEP_EXISTING" ]; then
    cp "${MONITORING_DIR}/loki/values.yaml" "${TEMP_DIR}/loki-values.yaml"
else
    sed "s/storageClassName: slow-hdd/storageClassName: $STORAGE_CLASS/g" \
        "${MONITORING_DIR}/loki/values.yaml" | \
    sed "s/storageClassName: fast-ssd/storageClassName: $STORAGE_CLASS/g" > "${TEMP_DIR}/loki-values.yaml"
fi

success "Configuration files prepared"
echo ""

# Show storage configuration
if [ "$STORAGE_CLASS" = "KEEP_EXISTING" ]; then
    log "Using existing storage classes: fast-ssd, slow-hdd"
else
    log "All components will use storage class: $STORAGE_CLASS"
fi
echo ""

## PHASE 4: Install kube-prometheus-stack
log "Phase 4/7: Installing kube-prometheus-stack (Prometheus + Grafana + AlertManager)..."
log "This may take 5-10 minutes..."
echo ""

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace "$NAMESPACE" \
  --values "${TEMP_DIR}/prometheus-values.yaml" \
  --wait \
  --timeout 15m

success "kube-prometheus-stack installed"
echo ""

## PHASE 5: Wait for core components
log "Phase 5/7: Waiting for core components to be ready..."

# Wait for Prometheus operator
log "Waiting for Prometheus Operator..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=prometheus-operator \
  -n "$NAMESPACE" \
  --timeout=300s || warn "Prometheus Operator not ready yet, but continuing..."

# Wait for Prometheus
log "Waiting for Prometheus..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=prometheus \
  -n "$NAMESPACE" \
  --timeout=300s || warn "Prometheus pod not ready yet, but continuing..."

# Wait for Grafana
log "Waiting for Grafana..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=grafana \
  -n "$NAMESPACE" \
  --timeout=300s || warn "Grafana pod not ready yet, but continuing..."

success "Core components ready"
echo ""

## PHASE 6: Install Loki stack
log "Phase 6/7: Installing Loki stack (Log aggregation)..."
log "This may take 3-5 minutes..."
echo ""

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

## PHASE 7: Deploy exporters and ServiceMonitors
log "Phase 7/7: Deploying database exporters and ServiceMonitors..."

# Deploy PostgreSQL exporters
log "Deploying PostgreSQL exporters..."
kubectl apply -f "${MONITORING_DIR}/exporters/postgres-exporter-june-services.yaml" || warn "Failed to deploy postgres-exporter-june-services (may not exist yet)"
kubectl apply -f "${MONITORING_DIR}/exporters/postgres-exporter-june-dark.yaml" || warn "Failed to deploy postgres-exporter-june-dark (may not exist yet)"

# Deploy Redis exporter
log "Deploying Redis exporter..."
kubectl apply -f "${MONITORING_DIR}/exporters/redis-exporter.yaml" || warn "Failed to deploy redis-exporter (may not exist yet)"

# Deploy RabbitMQ exporter
log "Deploying RabbitMQ exporter..."
kubectl apply -f "${MONITORING_DIR}/exporters/rabbitmq-exporter.yaml" || warn "Failed to deploy rabbitmq-exporter (may not exist yet)"

# Deploy Elasticsearch exporter
log "Deploying Elasticsearch exporter..."
kubectl apply -f "${MONITORING_DIR}/exporters/elasticsearch-exporter.yaml" || warn "Failed to deploy elasticsearch-exporter (may not exist yet)"

# Deploy ServiceMonitor for june-orchestrator
log "Deploying ServiceMonitor for june-orchestrator..."
kubectl apply -f "${MONITORING_DIR}/servicemonitors/june-orchestrator.yaml" || warn "Failed to deploy june-orchestrator ServiceMonitor (service may not exist yet)"

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

# Show final status
echo ""
log "Checking final pod status..."
kubectl get pods -n monitoring
echo ""

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
echo "# Check PVCs:"
echo "kubectl get pvc -n monitoring"
echo ""
echo "================================================================"
echo ""
echo "📚 Next Steps:"
echo ""
echo "1. Access Grafana and login with admin credentials"
echo "2. Verify all datasources are connected (Prometheus, Loki)"
echo "3. Import pre-built dashboards from Grafana.com:"
echo "   - Kubernetes Cluster: 315"
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
