# June Platform Observability Stack

Complete monitoring solution for Kubernetes cluster and all services using the Grafana LGTM stack.

## Overview

This directory contains all configuration files for the observability stack:

```
monitoring/
├── prometheus/          # Prometheus + Grafana + AlertManager config
│   └── values.yaml      # Helm values for kube-prometheus-stack
├── loki/                # Log aggregation config
│   └── values.yaml      # Helm values for Loki + Promtail
├── exporters/           # Database metric exporters
│   ├── postgres-exporter-june-services.yaml
│   ├── postgres-exporter-june-dark.yaml
│   ├── redis-exporter.yaml
│   ├── rabbitmq-exporter.yaml
│   └── elasticsearch-exporter.yaml
├── servicemonitors/     # Prometheus ServiceMonitor definitions
│   └── june-orchestrator.yaml
├── alerts/              # Custom alert rules
│   └── june-platform-alerts.yaml
└── README.md            # This file
```

## Quick Start

### Prerequisites

- Kubernetes cluster running
- `kubectl` configured
- `helm` installed
- `config.env` file with DOMAIN variable set

### Installation

**One-command deployment:**

```bash
cd scripts/install/monitoring
./install-observability-stack.sh
```

This script will:
1. Add Helm repositories (prometheus-community, grafana)
2. Create `monitoring` namespace
3. Install kube-prometheus-stack (Prometheus, Grafana, AlertManager)
4. Install Loki stack (Loki, Promtail)
5. Deploy all database exporters
6. Deploy ServiceMonitors
7. Deploy custom alert rules

**Installation time:** ~10-15 minutes

### Access

After installation, access the services:

```bash
# Get Grafana admin password
kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode; echo

# Access via ingress (if configured)
https://grafana.yourdomain.com
https://prometheus.yourdomain.com
https://alertmanager.yourdomain.com

# Or port-forward
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093
```

## What Gets Monitored

### Kubernetes Cluster
- ✅ Node resources (CPU, memory, disk, network)
- ✅ Pod status and health
- ✅ PVC usage
- ✅ API server performance
- ✅ etcd health
- ✅ Scheduler and kubelet metrics

### June Platform Services
- ✅ **June Orchestrator**: HTTP metrics, conversation analytics (via `/metrics` endpoint)
- ✅ **Keycloak**: Authentication metrics
- ✅ **PostgreSQL** (june-services): Database performance
- ✅ **TTS/STT** (external): Via remote write configuration

### June Dark OSINT Platform
- ✅ **PostgreSQL**: Database performance
- ✅ **Redis**: Cache metrics
- ✅ **RabbitMQ**: Queue depth, message rates
- ✅ **Elasticsearch**: Cluster health, query performance
- ✅ **Neo4j**: Graph database metrics (TODO: add exporter)
- ✅ **MinIO**: Storage metrics (TODO: add exporter)
- ✅ **Collector/Enricher**: Application metrics (TODO: add /metrics endpoints)

### Media Stack
- ⏳ TODO: Add exporters for Jellyfin, Sonarr, Radarr, etc.

## Pre-Built Dashboards

The following dashboards are automatically imported:

1. **Kubernetes / Compute Resources / Cluster** (ID: 7249)
2. **Kubernetes / Resources / Namespace** (ID: 11454)
3. **Kubernetes / Resources / Pod** (ID: 15760)
4. **Node Exporter Full** (ID: 1860)
5. **Nginx Ingress Controller** (ID: 9614)

### Recommended Dashboards to Import

Go to Grafana → Dashboards → Import and add these IDs:

- **PostgreSQL**: 9628
- **Redis**: 11835
- **RabbitMQ**: 10991
- **Elasticsearch**: 14191
- **Loki Dashboard**: 13639

## Alert Rules

### Critical Alerts (Page/SMS)
- Database down (PostgreSQL, Redis, RabbitMQ)
- High HTTP error rate (>5%)
- Disk space critical (<5%)
- PVC almost full (<10%)

### Warning Alerts (Slack/Email)
- High memory usage (>85%)
- High CPU usage (>80%)
- Pod not ready (15 minutes)
- Container restarting frequently
- PostgreSQL connection pool high (>80%)
- Redis memory usage high (>90%)
- RabbitMQ queue growing (>1000 messages)
- Elasticsearch cluster yellow
- Slow HTTP responses (p95 > 1s)

### Info Alerts (Log)
- Certificate expiring soon (<7 days)
- PostgreSQL slow queries

## Configuration

### Domain Configuration

Before installation, update `config.env`:

```bash
DOMAIN=yourdomain.com
```

The installation script will automatically configure ingresses for:
- `grafana.yourdomain.com`
- `prometheus.yourdomain.com`
- `alertmanager.yourdomain.com`

### Storage Configuration

Default storage requirements:
- Prometheus: 50Gi (slow-hdd) - 15 days retention
- Grafana: 5Gi (fast-ssd) - dashboard storage
- Loki: 50Gi (slow-hdd) - 7 days retention
- AlertManager: 5Gi (fast-ssd) - alert history

To change storage size, edit:
- `prometheus/values.yaml` → `prometheus.prometheusSpec.storageSpec`
- `loki/values.yaml` → `loki.persistence.size`

### Retention Configuration

**Metrics (Prometheus):**
Edit `prometheus/values.yaml`:
```yaml
prometheus:
  prometheusSpec:
    retention: 15d        # Change to desired retention
    retentionSize: "45GB" # Max storage before oldest deleted
```

**Logs (Loki):**
Edit `loki/values.yaml`:
```yaml
loki:
  config:
    chunk_store_config:
      max_look_back_period: 168h  # 7 days
    table_manager:
      retention_period: 168h      # 7 days
```

### AlertManager Notifications

Configure Slack/Email notifications by editing `prometheus/values.yaml`:

```yaml
alertmanager:
  config:
    receivers:
      - name: 'critical'
        slack_configs:
          - api_url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'
            channel: '#alerts-critical'
            title: '🚨 CRITICAL: {{ .GroupLabels.alertname }}'

        email_configs:
          - to: 'ops-team@yourdomain.com'
            from: 'alertmanager@yourdomain.com'
            smarthost: 'smtp.gmail.com:587'
            auth_username: 'your-email@gmail.com'
            auth_password: 'your-app-password'
```

Then upgrade the Helm release:

```bash
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values prometheus/values.yaml
```

## Verification

### Check Installation Status

```bash
# All pods should be Running
kubectl get pods -n monitoring

# Expected pods:
# - prometheus-kube-prometheus-stack-prometheus-0
# - kube-prometheus-stack-grafana-xxx
# - kube-prometheus-stack-alertmanager-0
# - kube-prometheus-stack-operator-xxx
# - kube-prometheus-stack-kube-state-metrics-xxx
# - prometheus-node-exporter-xxx (one per node)
# - loki-0
# - loki-promtail-xxx (one per node)
```

### Check ServiceMonitors

```bash
# List all ServiceMonitors
kubectl get servicemonitors -A

# Expected ServiceMonitors:
# - june-services: june-orchestrator, postgres-exporter
# - june-dark: postgres-exporter, redis-exporter, rabbitmq-exporter, elasticsearch-exporter
# - monitoring: (many default ones from kube-prometheus-stack)
```

### Verify Prometheus Targets

```bash
# Port-forward Prometheus
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090

# Open http://localhost:9090/targets
# All targets should show "UP" state
```

### Check Loki Logs

```bash
# Query recent logs
kubectl port-forward -n monitoring svc/loki 3100:3100

# Test query
curl -G -s "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={namespace="june-services"}' \
  --data-urlencode 'limit=10'
```

## Troubleshooting

### Prometheus not scraping targets

**Problem:** Targets show as "DOWN" in Prometheus

**Solution:**
1. Check ServiceMonitor labels match Prometheus selector:
   ```bash
   kubectl get servicemonitor <name> -n <namespace> -o yaml
   # Should have label: release: kube-prometheus-stack
   ```

2. Check pod has `/metrics` endpoint:
   ```bash
   kubectl port-forward <pod-name> 8080:8080
   curl http://localhost:8080/metrics
   ```

3. Check Prometheus logs:
   ```bash
   kubectl logs -n monitoring prometheus-kube-prometheus-stack-prometheus-0
   ```

### Grafana datasource not working

**Problem:** "Error reading Prometheus" or "Error reading Loki"

**Solution:**
1. Check datasource URL in Grafana → Configuration → Data Sources
   - Prometheus: `http://kube-prometheus-stack-prometheus:9090`
   - Loki: `http://loki:3100`

2. Test connectivity from Grafana pod:
   ```bash
   kubectl exec -it -n monitoring <grafana-pod> -- curl http://loki:3100/ready
   ```

### Loki not receiving logs

**Problem:** No logs showing in Grafana Explore

**Solution:**
1. Check Promtail is running on all nodes:
   ```bash
   kubectl get pods -n monitoring -l app=promtail
   ```

2. Check Promtail logs:
   ```bash
   kubectl logs -n monitoring -l app=promtail
   ```

3. Verify Promtail can reach Loki:
   ```bash
   kubectl exec -it -n monitoring <promtail-pod> -- curl http://loki:3100/ready
   ```

### Exporter pod failing

**Problem:** Exporter pod in CrashLoopBackOff

**Solution:**
1. Check logs:
   ```bash
   kubectl logs -n <namespace> <exporter-pod>
   ```

2. Common issues:
   - Wrong database credentials (check DATA_SOURCE_NAME in exporter YAML)
   - Database not accessible (check service name and port)
   - Database not ready yet (wait for database pod to be ready)

### High resource usage

**Problem:** Prometheus/Loki using too much resources

**Solution:**
1. Reduce retention period
2. Reduce scrape interval (change from 30s to 60s)
3. Disable unused exporters
4. Reduce log collection (exclude noisy namespaces in Promtail config)

## Maintenance

### Backup Configuration

**Important files to backup:**
- `prometheus/values.yaml` (Prometheus/Grafana config)
- `loki/values.yaml` (Loki config)
- Custom dashboards (export from Grafana UI)
- Alert rules (`alerts/*.yaml`)

### Upgrade

```bash
# Upgrade Prometheus stack
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values prometheus/values.yaml

# Upgrade Loki stack
helm upgrade loki grafana/loki-stack \
  --namespace monitoring \
  --values loki/values.yaml
```

### Uninstall

```bash
# Remove Helm releases
helm uninstall kube-prometheus-stack -n monitoring
helm uninstall loki -n monitoring

# Remove exporters
kubectl delete -f exporters/
kubectl delete -f servicemonitors/
kubectl delete -f alerts/

# Remove namespace (will delete PVCs!)
kubectl delete namespace monitoring
```

## Resource Usage

Expected resource consumption:

| Component | CPU | Memory | Storage |
|-----------|-----|--------|---------|
| Prometheus | 500m-2000m | 2-8Gi | 50Gi |
| Grafana | 100m-500m | 256Mi-1Gi | 5Gi |
| Loki | 500m-1000m | 1-4Gi | 50Gi |
| Promtail (per node) | 50m-100m | 128-256Mi | - |
| AlertManager | 50m-200m | 128-512Mi | 5Gi |
| Exporters (each) | 50m-200m | 64-256Mi | - |
| **TOTAL** | **~1.4-4 cores** | **~4-14Gi** | **110Gi** |

## Next Steps

1. ✅ **Access Grafana** and change admin password
2. ✅ **Import additional dashboards** (PostgreSQL, Redis, etc.)
3. ✅ **Configure AlertManager** notifications (Slack/Email)
4. ⏳ **Create custom dashboards** for June Platform services
5. ⏳ **Add missing exporters** (Neo4j, MinIO, Media Stack)
6. ⏳ **Set up remote write** for external TTS/STT services
7. ⏳ **Configure retention** based on storage capacity

## Documentation

- **Full Design**: `../../docs/OBSERVABILITY-STACK-DESIGN.md`
- **Prometheus**: https://prometheus.io/docs/
- **Grafana**: https://grafana.com/docs/
- **Loki**: https://grafana.com/docs/loki/
- **kube-prometheus-stack**: https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review Prometheus/Grafana/Loki logs
3. Consult official documentation
4. Open issue in June Platform repository
