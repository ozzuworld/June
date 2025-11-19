# ServiceMonitors

ServiceMonitors tell Prometheus which services to scrape for metrics.

## Deployed ServiceMonitors

### June Platform Services
- **june-orchestrator.yaml**: Scrapes conversation metrics from orchestrator (already has /metrics endpoint)

### Database Exporters (deployed separately)
After deploying the exporters (in `../exporters/`), these ServiceMonitors will be created automatically by the exporter Helm charts:

- PostgreSQL Exporter (june-services namespace)
- PostgreSQL Exporter (june-dark namespace)
- Redis Exporter (june-dark namespace)
- RabbitMQ Exporter (june-dark namespace)
- Elasticsearch Exporter (june-dark namespace)

## How ServiceMonitors Work

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-service
  labels:
    release: kube-prometheus-stack  # Must match Prometheus release name
spec:
  selector:
    matchLabels:
      app: my-service  # Matches Kubernetes Service labels
  endpoints:
  - port: http
    path: /metrics      # Metrics endpoint path
    interval: 30s       # Scrape every 30 seconds
```

## Verifying ServiceMonitors

Check if Prometheus is discovering your ServiceMonitors:

```bash
# List all ServiceMonitors
kubectl get servicemonitors -A

# Check Prometheus targets
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
# Open: http://localhost:9090/targets
```

## Adding New ServiceMonitors

To monitor a new service:

1. Ensure your service exports metrics at `/metrics` (Prometheus format)
2. Create a Kubernetes Service for your deployment
3. Create a ServiceMonitor matching your Service labels
4. Add label `release: kube-prometheus-stack` to ServiceMonitor

Example:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-new-service
  namespace: my-namespace
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: my-new-service
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
```
