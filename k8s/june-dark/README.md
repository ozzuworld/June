# June Dark OSINT Framework + OpenCTI Integration

Complete Kubernetes deployment for June Dark OSINT Framework with OpenCTI integration.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    June Dark OSINT Framework                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   │
│  │  Collector   │──▶│  Enricher    │──▶│ Orchestrator │   │
│  │              │   │              │   │              │   │
│  │ Web Crawling │   │ Extract IOCs │   │   Control    │   │
│  │ Data Collect │   │ Analyze Data │   │   Plane      │   │
│  └──────────────┘   └──────────────┘   └──────────────┘   │
│         │                   │                   │           │
│         └───────────────────┴───────────────────┘           │
│                             ▼                                │
│                    ┌─────────────────┐                      │
│                    │   RabbitMQ      │                      │
│                    │ Message Queue   │                      │
│                    └─────────────────┘                      │
│                             │                                │
│                             ▼                                │
│                   ┌──────────────────┐                      │
│                   │ OpenCTI Connector│                      │
│                   │                  │                      │
│                   │ STIX 2.1 Convert │                      │
│                   └──────────────────┘                      │
│                             │                                │
└─────────────────────────────┼────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                         OpenCTI                              │
├─────────────────────────────────────────────────────────────┤
│  Indicators │ Observables │ Reports │ Incidents             │
└─────────────────────────────────────────────────────────────┘
```

## Components

### June Dark Services
- **Orchestrator**: Central API and control plane
- **Collector**: Web crawling and data collection
- **Enricher**: Extract URLs, IPs, domains, emails from collected content
- **Ops UI**: Operations dashboard
- **OpenCTI Connector**: STIX 2.1 conversion and OpenCTI integration

### Infrastructure
- **Elasticsearch**: Full-text search and analytics
- **PostgreSQL**: Relational data (artifacts, alerts, watchlists)
- **Neo4j**: Graph database for entity relationships
- **Redis**: Caching and session management
- **RabbitMQ**: Message queue for async processing
- **MinIO**: Object storage for artifacts
- **Kibana**: Analytics and visualization

## Prerequisites

1. **Kubernetes cluster** (tested on K3s/K8s)
2. **kubectl** configured
3. **OpenCTI already deployed** (run `scripts/install/07.1-opencti.sh` first)
4. **Docker** for building images
5. **Ingress controller** (nginx)
6. **Wildcard TLS certificate** configured

## Quick Start

### 1. Build Docker Images

```bash
# Set your registry (default: ghcr.io/ozzuworld)
export DOCKER_REGISTRY=ghcr.io/yourusername
export DOCKER_TAG=latest

# Build all images
./scripts/install/build-june-dark-images.sh
```

### 2. Deploy June Dark + OpenCTI Integration

```bash
# Deploy everything (infrastructure + services + connector)
./scripts/install/07.2-june-dark-opencti.sh
```

The script will:
1. ✅ Retrieve OpenCTI credentials
2. ✅ Create namespace and config
3. ✅ Create persistent volumes
4. ✅ Deploy infrastructure (ES, PG, Neo4j, Redis, RabbitMQ, MinIO)
5. ✅ Deploy June Dark services
6. ✅ Configure OpenCTI connector
7. ✅ Create ingress

### 3. Verify Deployment

```bash
# Check all pods
kubectl get pods -n june-dark

# Check services
kubectl get svc -n june-dark

# Check ingress
kubectl get ingress -n june-dark
```

## Access Points

Based on your domain (e.g., `ozzu.world`):

- **Main API**: https://june.ozzu.world
- **Dashboard**: https://june.ozzu.world/dashboard
- **Kibana**: https://kibana.ozzu.world
- **Neo4j**: https://neo4j.ozzu.world
- **OpenCTI**: https://dark.ozzu.world

## Default Credentials

### PostgreSQL
- User: `juneadmin`
- Password: `juneP@ssw0rd2024`
- Database: `june_osint`

### Neo4j
- User: `neo4j`
- Password: `juneN3o4j2024`

### RabbitMQ
- User: `juneadmin`
- Password: `juneR@bbit2024`
- Management: http://rabbitmq.june-dark:15672

### MinIO
- User: `juneadmin`
- Password: `juneM1ni0P@ss2024`
- Console: http://minio.june-dark:9001

## OpenCTI Integration

### How It Works

1. **Data Collection**: Collector crawls websites and stores artifacts
2. **Enrichment**: Enricher extracts IOCs (URLs, IPs, domains, emails)
3. **Queue**: Enriched data is published to RabbitMQ
4. **Connector**: OpenCTI connector consumes enriched data
5. **STIX Conversion**: Connector converts to STIX 2.1 format
6. **OpenCTI**: Data is sent to OpenCTI as Observables/Indicators

### Data Mapping

| June Dark Data | OpenCTI Entity | Type |
|----------------|----------------|------|
| URLs | Observable | `url:value` |
| IP Addresses | Observable | `ipv4-addr:value` |
| Domains | Observable | `domain-name:value` |
| Email Addresses | Observable | `email-addr:value` |
| Alerts | Incident | STIX Incident |
| Extracted Content | Note | STIX Note |
| Full Report | Report | STIX Report |

### Connector Configuration

Edit `k8s/june-dark/12-opencti-connector.yaml` to customize:

```yaml
data:
  # Confidence level for created indicators
  CONNECTOR_CONFIDENCE_LEVEL: "75"

  # What to create in OpenCTI
  CREATE_INDICATORS: "true"
  CREATE_OBSERVABLES: "true"
  CREATE_NOTES: "true"
  CREATE_REPORTS: "true"

  # Entity mapping
  MAP_URLS_AS_OBSERVABLES: "true"
  MAP_IPS_AS_OBSERVABLES: "true"
  MAP_DOMAINS_AS_OBSERVABLES: "true"
  MAP_EMAILS_AS_OBSERVABLES: "true"
  MAP_ALERTS_AS_INCIDENTS: "true"
```

## Monitoring

### Check Logs

```bash
# Orchestrator logs
kubectl logs -f deployment/orchestrator -n june-dark

# Enricher logs
kubectl logs -f deployment/enricher -n june-dark

# OpenCTI connector logs
kubectl logs -f deployment/opencti-connector -n june-dark

# All logs
kubectl logs -f -l app.kubernetes.io/instance=june-dark -n june-dark
```

### Health Checks

```bash
# Orchestrator health
curl https://june.ozzu.world/health

# Enricher health
curl http://enricher.june-dark:9010/health

# OpenCTI connector health
curl http://opencti-connector.june-dark:8000/health

# OpenCTI connector metrics
curl http://opencti-connector.june-dark:8000/metrics
```

### Database Access

```bash
# PostgreSQL
kubectl exec -it deployment/postgres -n june-dark -- psql -U juneadmin -d june_osint

# Neo4j
kubectl port-forward svc/neo4j 7474:7474 7687:7687 -n june-dark
# Open http://localhost:7474

# Elasticsearch
kubectl port-forward svc/elasticsearch 9200:9200 -n june-dark
curl http://localhost:9200/_cat/indices
```

## Usage Examples

### 1. Create a Crawl Job

```bash
curl -X POST https://june.ozzu.world/api/v1/crawl/start \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "https://example.com",
    "max_depth": 2,
    "max_pages": 50
  }'
```

### 2. Create a Watchlist

```bash
curl -X POST https://june.ozzu.world/api/v1/alerts/watchlist \
  -H "Content-Type: application/json" \
  -d '{
    "name": "API Keys Detection",
    "pattern": "api[_-]?key",
    "is_regex": true,
    "priority": "high"
  }'
```

### 3. Check OpenCTI for Data

1. Go to https://dark.ozzu.world
2. Navigate to **Data** → **Observations**
3. Look for entities with label `june-dark`
4. Check **Analysis** → **Reports** for June Dark reports

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl describe pod <pod-name> -n june-dark

# Check events
kubectl get events -n june-dark --sort-by='.lastTimestamp'
```

### Connector Not Sending Data

```bash
# Check connector logs
kubectl logs -f deployment/opencti-connector -n june-dark

# Verify RabbitMQ connection
kubectl exec -it deployment/rabbitmq -n june-dark -- rabbitmqctl list_queues

# Check OpenCTI token
kubectl get secret opencti-connector-secret -n june-dark -o yaml
```

### Storage Issues

```bash
# Check PVCs
kubectl get pvc -n june-dark

# Check PVs
kubectl get pv | grep june-dark

# Check disk space
df -h /mnt/june-dark/*
```

## Scaling

### Scale Workers

```bash
# Scale enricher workers
kubectl scale deployment enricher --replicas=3 -n june-dark

# Scale collector workers
kubectl scale deployment collector --replicas=4 -n june-dark
```

### Resource Limits

Edit deployments to adjust resources:

```yaml
resources:
  requests:
    memory: "2Gi"
    cpu: "1000m"
  limits:
    memory: "4Gi"
    cpu: "2000m"
```

## Cleanup

### Remove Everything

```bash
# Delete namespace (removes all resources)
kubectl delete namespace june-dark

# Remove persistent volumes
kubectl delete pv june-dark-elasticsearch-pv june-dark-postgres-pv \
  june-dark-neo4j-pv june-dark-minio-pv june-dark-redis-pv june-dark-rabbitmq-pv

# Remove data
sudo rm -rf /mnt/june-dark/
```

### Remove Only Services (Keep Data)

```bash
# Delete deployments
kubectl delete deployment --all -n june-dark

# Keep namespace and PVCs for later
```

## Development

### Local Testing

```bash
# Port forward services
kubectl port-forward svc/orchestrator 8080:8080 -n june-dark
kubectl port-forward svc/enricher 9010:9010 -n june-dark
kubectl port-forward svc/elasticsearch 9200:9200 -n june-dark

# Test locally
curl http://localhost:8080/health
```

### Rebuild Single Service

```bash
# Rebuild enricher
docker build -t ghcr.io/ozzuworld/june-dark-enricher:latest \
  June/services/june-dark/services/enricher

docker push ghcr.io/ozzuworld/june-dark-enricher:latest

# Restart deployment
kubectl rollout restart deployment/enricher -n june-dark
```

## Security Considerations

⚠️ **IMPORTANT**: The default configuration uses hardcoded passwords for development.

For production:

1. **Use Kubernetes Secrets** for all credentials
2. **Enable TLS** for all internal services
3. **Enable authentication** on Elasticsearch, RabbitMQ, MinIO
4. **Use network policies** to restrict pod-to-pod communication
5. **Rotate credentials** regularly
6. **Enable RBAC** on Neo4j
7. **Use vault** for secret management

## Support

- **Documentation**: See deployment info at `/root/.june-dark-deployment`
- **Logs**: `kubectl logs -f deployment/<service> -n june-dark`
- **Status**: `kubectl get all -n june-dark`
