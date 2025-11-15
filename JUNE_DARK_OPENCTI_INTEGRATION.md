# June Dark + OpenCTI Integration Guide

Complete integration between June Dark OSINT Framework and OpenCTI for automated threat intelligence management.

## 🎯 What This Integration Does

**June Dark OSINT Framework** collects and enriches OSINT data from various sources:
- Web crawling
- Content extraction
- IOC identification (URLs, IPs, domains, emails)
- Alert generation

**OpenCTI Connector** automatically converts June Dark data to STIX 2.1 and pushes to OpenCTI:
- Creates Observables for all extracted IOCs
- Generates Indicators with patterns
- Creates Reports summarizing findings
- Converts Alerts to Incidents
- Maintains full relationship graph

## 📋 Prerequisites

1. ✅ Kubernetes cluster running (K3s/K8s)
2. ✅ OpenCTI deployed (via `scripts/install/07.1-opencti.sh`)
3. ✅ Docker for building images
4. ✅ Ingress controller (nginx)
5. ✅ Wildcard TLS certificate

## 🚀 Quick Deployment

### Step 1: Build Docker Images

```bash
cd /home/user/June

# Build all June Dark images
./scripts/install/build-june-dark-images.sh

# When prompted, push to registry (or configure your own)
```

### Step 2: Deploy June Dark + Connector

```bash
# Deploy complete stack (infrastructure + services + OpenCTI integration)
./scripts/install/07.2-june-dark-opencti.sh
```

This deploys:
- ✅ Elasticsearch (search & analytics)
- ✅ PostgreSQL (metadata storage)
- ✅ Neo4j (graph relationships)
- ✅ Redis (caching)
- ✅ RabbitMQ (message queue)
- ✅ MinIO (object storage)
- ✅ Kibana (visualization)
- ✅ June Dark Orchestrator
- ✅ June Dark Collector
- ✅ June Dark Enricher
- ✅ June Dark Ops UI
- ✅ **OpenCTI Connector** (STIX bridge)

### Step 3: Verify Integration

```bash
# Check all pods are running
kubectl get pods -n june-dark

# Check connector is connected to OpenCTI
kubectl logs -f deployment/opencti-connector -n june-dark

# Should see:
# ✓ Connected to OpenCTI
# ✓ Connected to June Dark RabbitMQ
# Listening for messages...
```

## 🔄 Data Flow

```
1. Web Source
    ↓
2. June Dark Collector
    ↓ (stores artifacts)
3. MinIO + PostgreSQL
    ↓ (triggers enrichment)
4. June Dark Enricher
    ↓ (extracts IOCs: URLs, IPs, domains, emails)
5. RabbitMQ Queue
    ↓ (enrichment.results)
6. OpenCTI Connector
    ↓ (converts to STIX 2.1)
7. OpenCTI Platform
    ↓
8. Observables, Indicators, Reports, Incidents
```

## 📊 What Gets Created in OpenCTI

### From Enriched Data

| June Dark Data | OpenCTI Type | STIX Pattern |
|----------------|--------------|--------------|
| URLs | Observable + Indicator | `[url:value = 'https://...']` |
| IP Addresses | Observable + Indicator | `[ipv4-addr:value = '1.2.3.4']` |
| Domains | Observable + Indicator | `[domain-name:value = 'example.com']` |
| Email Addresses | Observable | `[email-addr:value = 'user@example.com']` |
| Extracted Content | Note | Full text preview |
| Collection Summary | Report | Links all related entities |

### From Alerts

| June Dark Alert | OpenCTI Type | Contains |
|-----------------|--------------|----------|
| Watchlist Match | Incident | Matched pattern, severity, confidence |
| Alert Context | Note | Matched text snippet |

### Metadata

All entities include:
- **Labels**: `["osint", "june-dark"]`
- **Source**: "June Dark OSINT Framework"
- **Confidence**: 75% (configurable)
- **External References**: Original URL
- **Relationships**: Connected via STIX relationships

## 🎮 Usage Examples

### Example 1: Crawl a Website

```bash
# Start a crawl job
curl -X POST https://june.ozzu.world/api/v1/crawl/start \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "https://pastebin.com/recent",
    "max_depth": 1,
    "max_pages": 20
  }'

# After crawling completes:
# 1. Check June Dark Dashboard: https://june.ozzu.world/dashboard
# 2. Check OpenCTI: https://dark.ozzu.world
# 3. Navigate to Data → Observations
# 4. Filter by label: "june-dark"
# 5. See all extracted URLs, IPs, domains
```

### Example 2: Set Up Watchlist

```bash
# Create watchlist for API keys
curl -X POST https://june.ozzu.world/api/v1/alerts/watchlist \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Exposed API Keys",
    "description": "Detect leaked API keys",
    "pattern": "api[_-]?key|apikey",
    "is_regex": true,
    "priority": "high",
    "alert_enabled": true
  }'

# When API key is found:
# 1. Alert created in June Dark
# 2. Incident created in OpenCTI
# 3. Severity mapped (high → high)
# 4. Matched text included in Note
```

### Example 3: View in OpenCTI

1. **Access OpenCTI**: https://dark.ozzu.world
2. **Login** with credentials from `/root/.opencti-credentials`
3. **Navigate**:
   - **Data → Observations → Observables**: See all URLs, IPs, domains, emails
   - **Analysis → Reports**: See collection summaries
   - **Events → Incidents**: See alerts from watchlists
4. **Filter by source**: "June Dark"
5. **Explore relationships**: Click on any entity to see graph

## ⚙️ Configuration

### Connector Settings

Edit `/home/user/June/k8s/june-dark/12-opencti-connector.yaml`:

```yaml
data:
  # Confidence level for indicators (0-100)
  CONNECTOR_CONFIDENCE_LEVEL: "75"

  # What to create in OpenCTI
  CREATE_INDICATORS: "true"        # Create Indicators with patterns
  CREATE_OBSERVABLES: "true"       # Create Observable entities
  CREATE_NOTES: "true"             # Create Notes with content
  CREATE_REPORTS: "true"           # Create summary Reports

  # Entity mapping
  MAP_URLS_AS_OBSERVABLES: "true"
  MAP_IPS_AS_OBSERVABLES: "true"
  MAP_DOMAINS_AS_OBSERVABLES: "true"
  MAP_EMAILS_AS_OBSERVABLES: "true"
  MAP_ALERTS_AS_INCIDENTS: "true"

  # TLP marking
  MAX_TLP: "TLP:AMBER"             # Maximum TLP for data
```

Apply changes:
```bash
kubectl apply -f k8s/june-dark/12-opencti-connector.yaml
kubectl rollout restart deployment/opencti-connector -n june-dark
```

### June Dark Features

Enable/disable features in `/home/user/June/k8s/june-dark/01-configmap.yaml`:

```yaml
data:
  FEATURE_OPENCTI: "true"          # ✅ OpenCTI integration
  FEATURE_DARK_WEB: "false"        # Dark web crawling
  FEATURE_MALWARE_ANALYSIS: "false" # Malware scanning
  FEATURE_SOCIAL_API: "false"      # Social media APIs
```

## 🔍 Monitoring

### Health Checks

```bash
# All services
kubectl get pods -n june-dark

# Connector status
kubectl logs -f deployment/opencti-connector -n june-dark | grep "✓"

# Metrics
curl http://opencti-connector.june-dark:8000/metrics
```

### Metrics Exposed

```json
{
  "messages_processed": 1247,
  "messages_failed": 3,
  "bundles_sent": 1244,
  "uptime_seconds": 86400
}
```

### Common Log Messages

```
✓ Connected to OpenCTI
✓ STIX converter initialized
✓ Connected to June Dark RabbitMQ
Listening for messages on queue: enrichment.results
Received message: artifact-abc123
Converting enriched data to STIX: artifact-abc123
Created STIX bundle with 15 objects
Sending 15 STIX objects to OpenCTI
✓ Sent bundle to OpenCTI (artifact: artifact-abc123)
```

## 🐛 Troubleshooting

### Connector Not Receiving Data

```bash
# Check RabbitMQ queue
kubectl exec -it deployment/rabbitmq -n june-dark -- rabbitmqctl list_queues

# Should see: enrichment.results with messages

# Check enricher is publishing
kubectl logs -f deployment/enricher -n june-dark | grep "published"
```

### Data Not Appearing in OpenCTI

```bash
# Check connector logs for errors
kubectl logs -f deployment/opencti-connector -n june-dark | grep ERROR

# Verify OpenCTI token
kubectl get secret opencti-connector-secret -n june-dark -o jsonpath='{.data.OPENCTI_TOKEN}' | base64 -d

# Test OpenCTI connection
kubectl exec -it deployment/opencti-connector -n june-dark -- curl -H "Authorization: Bearer $TOKEN" https://dark.ozzu.world/graphql
```

### Connector Crash Loop

```bash
# Check pod status
kubectl describe pod -l app=opencti-connector -n june-dark

# Common issues:
# 1. Invalid OpenCTI token → Update secret
# 2. Can't reach RabbitMQ → Check network
# 3. Missing dependencies → Rebuild image
```

## 📦 Files Created

### Application Code
```
June/services/june-dark-opencti-connector/
├── Dockerfile
├── requirements.txt
└── app/
    ├── __init__.py
    ├── config.py           # Connector configuration
    ├── main.py             # Main worker
    └── stix_converter.py   # STIX 2.1 conversion logic
```

### Kubernetes Manifests
```
k8s/june-dark/
├── 00-namespace.yaml
├── 01-configmap.yaml
├── 02-storage.yaml
├── 03-elasticsearch.yaml
├── 04-postgres.yaml
├── 05-neo4j.yaml
├── 06-redis-rabbitmq.yaml
├── 07-minio.yaml
├── 08-orchestrator.yaml
├── 09-collector.yaml
├── 10-enricher.yaml
├── 11-ops-ui.yaml
├── 12-opencti-connector.yaml  ← OpenCTI Connector
├── 13-ingress.yaml
├── 14-postgres-init.yaml
├── 15-kibana.yaml
└── README.md
```

### Scripts
```
scripts/install/
├── 07.1-opencti.sh                    # Deploy OpenCTI
├── 07.2-june-dark-opencti.sh          # Deploy June Dark + Connector
└── build-june-dark-images.sh          # Build Docker images
```

## 🌐 Access Points

Based on domain `ozzu.world`:

| Service | URL | Purpose |
|---------|-----|---------|
| June Dark API | https://june.ozzu.world | Main API endpoint |
| Operations Dashboard | https://june.ozzu.world/dashboard | Monitoring UI |
| Kibana | https://kibana.ozzu.world | Analytics |
| Neo4j Browser | https://neo4j.ozzu.world | Graph visualization |
| **OpenCTI** | https://dark.ozzu.world | Threat intel platform |

## 🔐 Security Notes

⚠️ **Default configuration uses hardcoded passwords for development**

For production:
1. Use Kubernetes Secrets
2. Enable TLS everywhere
3. Implement RBAC
4. Rotate credentials
5. Use network policies
6. Enable authentication on all services

## 📚 Next Steps

1. **Start Collecting Data**: Create crawl jobs via API
2. **Set Up Watchlists**: Define patterns to watch for
3. **Monitor OpenCTI**: Check Data → Observations for IOCs
4. **Create Dashboards**: Use Kibana for analytics
5. **Explore Relationships**: Use Neo4j browser for graph analysis
6. **Review Incidents**: Check OpenCTI Events for alerts

## 🎓 Learning Resources

- **OpenCTI Docs**: https://docs.opencti.io
- **STIX 2.1 Spec**: https://docs.oasis-open.org/cti/stix/v2.1/
- **June Dark Source**: `/home/user/June/June/services/june-dark/`
- **Connector Source**: `/home/user/June/June/services/june-dark-opencti-connector/`

## 💡 Tips

1. **Start Small**: Crawl 10-20 pages initially to test
2. **Monitor Resources**: Watch Elasticsearch memory usage
3. **Tune Confidence**: Adjust `CONNECTOR_CONFIDENCE_LEVEL` based on source quality
4. **Use Labels**: Filter in OpenCTI by `june-dark` label
5. **Check Logs**: `kubectl logs -f deployment/opencti-connector -n june-dark`

---

**Status**: ✅ Ready for deployment
**Created**: $(date)
**Platform**: Kubernetes
**Integration**: June Dark → RabbitMQ → OpenCTI Connector → OpenCTI
