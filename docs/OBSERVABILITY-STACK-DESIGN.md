# Comprehensive Observability Stack for June Platform

## Executive Summary

This document outlines the complete observability solution for monitoring your Kubernetes cluster and all services running on it (June Platform, June Dark OSINT, Media Stack).

**Recommended Stack:** **Grafana LGTM Stack** (Loki, Grafana, Tempo, Mimir/Prometheus)
- Industry standard for Kubernetes observability
- Unified visualization in Grafana
- Complete coverage: metrics, logs, traces
- Cost-effective (all open-source)
- Easy integration with existing services

---

## Current State Analysis

### ✅ What You Already Have

| Component | Location | Purpose | Status |
|-----------|----------|---------|--------|
| **Elasticsearch** | june-dark namespace | Log storage for OSINT platform | ✅ Deployed |
| **Kibana** | june-dark namespace | Log visualization for OSINT | ✅ Deployed |
| **Prometheus metrics** | june-orchestrator code | Application-level metrics collection | ✅ Implemented |
| **Metrics endpoint** | `/metrics` in orchestrator | Exports Prometheus format metrics | ✅ Working |

### ❌ What's Missing

| Gap | Impact | Priority |
|-----|--------|----------|
| **Cluster-wide metrics** | Can't see node/pod resource usage | P1 - Critical |
| **Centralized logs** | Logs scattered across pods | P1 - Critical |
| **Service monitoring** | Can't monitor Media Stack, STT/TTS | P1 - Critical |
| **Alerting system** | No proactive notification of issues | P1 - Critical |
| **Unified dashboards** | Can't see full system health | P2 - High |
| **Distributed tracing** | Can't debug complex request flows | P3 - Medium |

---

## Recommended Observability Stack

### **Option 1: Grafana LGTM Stack** ⭐ **RECOMMENDED**

Complete, battle-tested, cloud-native observability platform.

```
┌────────────────────────────────────────────────────────────────┐
│                      GRAFANA LGTM STACK                         │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  📊 METRICS: Prometheus + Grafana Mimir                        │
│  ├─ Kube-state-metrics (cluster state)                        │
│  ├─ Node Exporter (node resources)                            │
│  ├─ cAdvisor (container metrics)                              │
│  ├─ Service Monitors (app metrics)                            │
│  └─ Prometheus Operator (automation)                          │
│                                                                 │
│  📝 LOGS: Grafana Loki + Promtail                             │
│  ├─ Promtail DaemonSet (log collection)                       │
│  ├─ Loki (log aggregation & storage)                          │
│  └─ LogQL (powerful query language)                           │
│                                                                 │
│  🔍 TRACES: Grafana Tempo (optional)                          │
│  ├─ OpenTelemetry collector                                   │
│  ├─ Tempo (trace storage)                                     │
│  └─ Distributed tracing                                       │
│                                                                 │
│  📈 VISUALIZATION: Grafana                                     │
│  ├─ Pre-built dashboards                                      │
│  ├─ Custom dashboards                                         │
│  ├─ Unified view of all data                                  │
│  └─ Alerting & notifications                                  │
│                                                                 │
│  🚨 ALERTING: AlertManager                                     │
│  ├─ Alert rules                                               │
│  ├─ Notification routing                                      │
│  ├─ Slack/Email/PagerDuty                                     │
│  └─ Alert grouping & silencing                                │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

**Why This Stack:**
- ✅ **Industry Standard** - Used by 80%+ of Kubernetes deployments
- ✅ **Complete Coverage** - Metrics, logs, traces in one place
- ✅ **Open Source** - No licensing costs
- ✅ **Easy to Deploy** - Single Helm chart (`kube-prometheus-stack`)
- ✅ **100+ Pre-built Dashboards** - Kubernetes, PostgreSQL, Redis, Nginx, etc.
- ✅ **Powerful Queries** - PromQL for metrics, LogQL for logs
- ✅ **Low Resource Usage** - Optimized for Kubernetes

---

## Architecture Design

### **Namespace Strategy**

```yaml
monitoring/          # New namespace for observability stack
├── Prometheus       # Metrics collection & storage
├── Grafana          # Visualization & dashboards
├── Loki             # Log aggregation
├── Promtail         # Log shipping (DaemonSet on all nodes)
├── AlertManager     # Alert routing & notification
└── Tempo (optional) # Distributed tracing
```

**Reasoning:** Separate namespace keeps monitoring independent from applications.

---

### **Data Flow Architecture**

```
┌─────────────────────────────────────────────────────────────────┐
│                        MONITORING PIPELINE                       │
└─────────────────────────────────────────────────────────────────┘

1️⃣ METRICS COLLECTION:

   Kubernetes API
        │
        ├──> Kube-state-metrics ──┐
        │                          │
   Node Metrics                    │
        │                          │
        ├──> Node Exporter ────────┤
        │                          │
   Container Stats                 ├──> Prometheus ──> Grafana
        │                          │      (Storage)
        ├──> cAdvisor ─────────────┤
        │                          │
   App Metrics (/metrics)          │
        │                          │
        └──> ServiceMonitor ───────┘

2️⃣ LOGS COLLECTION:

   Pod Logs (/var/log/pods/*)
        │
        ├──> Promtail (DaemonSet)
        │         │
        │         ├──> Add labels (namespace, pod, container)
        │         ├──> Parse structured logs
        │         │
        │         └──> Loki ──────> Grafana
        │              (Storage)
        │
        └──> Elasticsearch (june-dark only, optional)

3️⃣ ALERTING PIPELINE:

   Prometheus Rules
        │
        ├──> Evaluate every 1 minute
        │
        ├──> Alert triggered?
        │         │
        │         └──> AlertManager
        │                   │
        │                   ├──> Route to receiver
        │                   ├──> Group similar alerts
        │                   ├──> Throttle notifications
        │                   │
        │                   └──> Notify: Slack/Email/PagerDuty

4️⃣ VISUALIZATION:

   Grafana Dashboard
        │
        ├──> Query Prometheus (metrics)
        ├──> Query Loki (logs)
        ├──> Query Tempo (traces)
        │
        └──> Unified view of entire system
```

---

## What Will Be Monitored

### **1. Kubernetes Cluster Health**

**Metrics Collected:**
- ✅ Node CPU, memory, disk usage
- ✅ Pod status (Running, Pending, Failed, CrashLoopBackOff)
- ✅ Pod restarts and OOMKills
- ✅ PVC usage and available storage
- ✅ Network traffic (ingress/egress)
- ✅ API server performance
- ✅ etcd health
- ✅ Scheduler latency
- ✅ kubelet performance

**Pre-built Dashboards:**
- Kubernetes Cluster Overview
- Node Overview
- Pod Resource Usage
- Persistent Volumes
- Network Traffic
- API Server
- etcd

---

### **2. June Platform Services**

#### **June Orchestrator**
- ✅ HTTP request rate, latency, errors (from existing `/metrics` endpoint)
- ✅ Conversation metrics (already instrumented in code)
- ✅ WebSocket connections
- ✅ TTS/STT service latency
- ✅ Intent classification performance
- ✅ Session management
- ✅ Database connection pool usage

**Custom Dashboard:** June Platform Health

#### **Keycloak (IDP)**
- ✅ Login success/failure rate
- ✅ Token generation time
- ✅ Active sessions
- ✅ Memory/CPU usage
- ✅ Database connections

**Pre-built Dashboard:** Keycloak Overview

#### **PostgreSQL**
- ✅ Queries per second
- ✅ Active connections
- ✅ Transaction rate
- ✅ Cache hit ratio
- ✅ Slow queries
- ✅ Replication lag (if applicable)

**Pre-built Dashboard:** PostgreSQL Exporter

---

### **3. June Dark OSINT Platform**

#### **Core Services**
- ✅ PostgreSQL, Redis, RabbitMQ, Neo4j, Elasticsearch
- ✅ MinIO storage usage
- ✅ Collector performance (scraping rate, errors)
- ✅ Enricher processing rate
- ✅ OpenCTI connector status

**Custom Dashboard:** June Dark OSINT Pipeline

#### **Message Queue Health**
- ✅ RabbitMQ queue depth
- ✅ Message rate (publish/consume)
- ✅ Consumer lag
- ✅ Dead letter queue size

**Pre-built Dashboard:** RabbitMQ Overview

#### **Database Performance**
- ✅ Elasticsearch query performance
- ✅ Index size and shard health
- ✅ Neo4j query latency
- ✅ Graph database size

**Pre-built Dashboards:**
- Elasticsearch Exporter
- Neo4j Exporter

---

### **4. Media Stack**

#### **Jellyfin**
- ✅ Concurrent streams
- ✅ Transcoding sessions
- ✅ API response time
- ✅ Storage usage

#### **Automation Services**
- ✅ Sonarr/Radarr/Lidarr download queue
- ✅ Prowlarr indexer health
- ✅ qBittorrent download speed, ratio
- ✅ Jellyseerr request queue

**Custom Dashboard:** Media Stack Overview

---

### **5. External Services (TTS/STT in other DC)**

**Via Remote Write:**
- ✅ TTS model loading time
- ✅ TTS synthesis latency
- ✅ STT transcription accuracy
- ✅ GPU utilization
- ✅ Voice cache size

**Setup:** Configure TTS/STT services to push metrics to central Prometheus

---

## Resource Requirements

### **Monitoring Stack Resource Usage**

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit | Storage |
|-----------|-------------|-----------|----------------|--------------|---------|
| Prometheus | 500m | 2000m | 2Gi | 8Gi | 50Gi (15 days retention) |
| Grafana | 100m | 500m | 256Mi | 1Gi | 5Gi |
| Loki | 500m | 1000m | 1Gi | 4Gi | 50Gi (7 days retention) |
| Promtail (per node) | 50m | 100m | 128Mi | 256Mi | - |
| AlertManager | 50m | 200m | 128Mi | 512Mi | 5Gi |
| Kube-state-metrics | 100m | 200m | 128Mi | 256Mi | - |
| Node Exporter (per node) | 50m | 100m | 64Mi | 128Mi | - |
| **TOTAL** | **~1.4 cores** | **~4 cores** | **~4Gi** | **~14Gi** | **110Gi** |

**Notes:**
- Storage can use `slow-hdd` storage class
- Retention periods are configurable (longer = more storage)
- Resource usage scales with cluster size

---

## Installation Guide

### **Step 1: Install kube-prometheus-stack**

```bash
# Add Helm repository
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Create monitoring namespace
kubectl create namespace monitoring

# Install with custom values
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values /path/to/prometheus-values.yaml \
  --wait
```

### **Step 2: Install Loki Stack**

```bash
# Add Grafana Helm repository
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Install Loki + Promtail
helm install loki grafana/loki-stack \
  --namespace monitoring \
  --values /path/to/loki-values.yaml \
  --wait
```

### **Step 3: Configure ServiceMonitors**

```yaml
# Create ServiceMonitor for june-orchestrator
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: june-orchestrator
  namespace: june-services
spec:
  selector:
    matchLabels:
      app: june-orchestrator
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
```

### **Step 4: Access Grafana**

```bash
# Get Grafana admin password
kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode

# Port-forward to access
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80

# Or create Ingress for public access
```

---

## Pre-Built Dashboards Available

### **Kubernetes Dashboards** (Included with kube-prometheus-stack)

1. **Kubernetes / Compute Resources / Cluster**
   - Overall cluster CPU, memory, network usage
   - Pod count, resource requests vs limits
   - Node resource utilization

2. **Kubernetes / Compute Resources / Namespace (Pods)**
   - Per-namespace resource usage
   - Pod CPU/memory over time
   - Top consumers

3. **Kubernetes / Compute Resources / Pod**
   - Individual pod metrics
   - Container resource usage
   - Network I/O

4. **Kubernetes / Networking / Cluster**
   - Cluster-wide network traffic
   - Pod-to-pod communication
   - Ingress/egress bandwidth

5. **Kubernetes / Persistent Volumes**
   - PV/PVC usage
   - Storage capacity and utilization
   - I/O performance

### **Application Dashboards** (From Grafana.com)

6. **PostgreSQL Database** (ID: 9628)
   - Connections, transactions, queries
   - Cache hit ratio, buffer usage
   - Slow queries, locks

7. **Redis** (ID: 11835)
   - Commands per second
   - Memory usage, eviction rate
   - Key space statistics

8. **RabbitMQ** (ID: 10991)
   - Queue depth, message rate
   - Consumer performance
   - Connection status

9. **Elasticsearch** (ID: 14191)
   - Cluster health, shard status
   - Query performance
   - JVM heap usage

10. **Nginx Ingress Controller** (ID: 9614)
    - Request rate, latency, errors
    - Top endpoints
    - SSL certificate expiry

11. **Node Exporter Full** (ID: 1860)
    - CPU, memory, disk, network per node
    - System load, uptime
    - File system usage

### **Custom Dashboards to Create**

12. **June Platform Overview**
    - Orchestrator health
    - TTS/STT latency
    - Conversation metrics
    - Session count

13. **June Dark OSINT Pipeline**
    - Collector scraping rate
    - Enricher processing rate
    - Data flow through pipeline
    - Error rates by component

14. **Media Stack Health**
    - Jellyfin streams
    - Download queue status
    - Indexer health
    - Storage usage

---

## Alert Rules

### **Critical Alerts (Page immediately)**

```yaml
groups:
- name: critical
  rules:
  - alert: NodeDown
    expr: up{job="node-exporter"} == 0
    for: 5m
    annotations:
      summary: "Node {{ $labels.instance }} is down"

  - alert: PodCrashLooping
    expr: rate(kube_pod_container_status_restarts_total[15m]) > 0
    for: 5m
    annotations:
      summary: "Pod {{ $labels.pod }} is crash looping"

  - alert: HighMemoryUsage
    expr: (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes > 0.9
    for: 10m
    annotations:
      summary: "Node {{ $labels.instance }} memory usage > 90%"

  - alert: DiskSpaceRunningOut
    expr: node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} < 0.1
    for: 5m
    annotations:
      summary: "Node {{ $labels.instance }} disk space < 10%"

  - alert: DatabaseDown
    expr: up{job="postgresql"} == 0
    for: 2m
    annotations:
      summary: "PostgreSQL is down in {{ $labels.namespace }}"
```

### **Warning Alerts (Notify via Slack)**

```yaml
- name: warnings
  rules:
  - alert: HighCPUUsage
    expr: 100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
    for: 10m
    annotations:
      summary: "Node {{ $labels.instance }} CPU usage > 80%"

  - alert: PodNotReady
    expr: kube_pod_status_phase{phase!~"Running|Succeeded"} > 0
    for: 15m
    annotations:
      summary: "Pod {{ $labels.pod }} not ready for 15 minutes"

  - alert: HighErrorRate
    expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
    for: 5m
    annotations:
      summary: "High error rate (>5%) on {{ $labels.service }}"
```

---

## Integration with Existing Services

### **June Orchestrator** (Already has Prometheus metrics)

**Current implementation:**
```python
# June/services/june-orchestrator/app/services/metrics.py
# Already exports Prometheus format metrics

# Add ServiceMonitor to scrape:
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: june-orchestrator
  namespace: june-services
spec:
  selector:
    matchLabels:
      app: june-orchestrator
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
```

**No code changes needed!** Just add ServiceMonitor.

### **Elasticsearch (June Dark)**

**Two options:**

**Option 1:** Keep Kibana for logs, add Prometheus exporter for metrics
```bash
# Deploy elasticsearch-exporter
kubectl apply -f elasticsearch-exporter.yaml

# Creates /metrics endpoint that Prometheus scrapes
```

**Option 2:** Send logs to both Elasticsearch and Loki
```yaml
# Promtail can tail pod logs and send to Loki
# Elasticsearch continues receiving app logs
# Gives you both options
```

### **TTS/STT Services (External DC)**

**Option 1: Remote Write** (Recommended)
```yaml
# Configure TTS/STT Prometheus to push to central Prometheus
remote_write:
  - url: https://prometheus.yourdomain.com/api/v1/write
    basic_auth:
      username: remote_write_user
      password: <secret>
```

**Option 2: Federation**
```yaml
# Central Prometheus pulls from remote Prometheus
scrape_configs:
  - job_name: 'federate-tts-stt'
    honor_labels: true
    metrics_path: '/federate'
    params:
      'match[]':
        - '{job=~"tts|stt"}'
    static_configs:
      - targets:
        - 'prometheus.external-dc.com:9090'
```

---

## Cost-Benefit Analysis

### **Benefits**

| Benefit | Value |
|---------|-------|
| **Prevent downtime** | Early detection of issues (disk full, OOMKill imminent) |
| **Faster debugging** | Logs + metrics in one place = 10x faster root cause analysis |
| **Capacity planning** | Historical data shows growth trends, plan upgrades proactively |
| **SLA compliance** | Track uptime, response times, error rates |
| **Cost optimization** | Identify overprovisioned resources, rightsize deployments |

### **Costs**

| Cost | Value |
|------|-------|
| **Resources** | ~1.4 CPU cores, ~4Gi RAM, 110Gi storage |
| **Time to deploy** | 2-4 hours (with pre-configured values) |
| **Maintenance** | 1-2 hours/month (dashboard updates, alert tuning) |

**ROI:** Typically pays for itself in **< 1 week** by preventing a single outage.

---

## Recommended Deployment Order

### **Phase 1: Core Monitoring (Week 1)**
1. ✅ Install kube-prometheus-stack (Prometheus + Grafana + AlertManager)
2. ✅ Verify cluster metrics are being collected
3. ✅ Import pre-built Kubernetes dashboards
4. ✅ Set up basic alerts (node down, pod crash looping)
5. ✅ Configure Slack/Email notifications

**Expected result:** Can see cluster health and resource usage

### **Phase 2: Application Monitoring (Week 2)**
1. ✅ Add ServiceMonitor for june-orchestrator (uses existing `/metrics`)
2. ✅ Deploy PostgreSQL exporter for databases
3. ✅ Deploy Redis exporter
4. ✅ Deploy RabbitMQ exporter (June Dark)
5. ✅ Deploy Elasticsearch exporter (June Dark)
6. ✅ Import application dashboards

**Expected result:** Can see all service health and performance

### **Phase 3: Log Aggregation (Week 3)**
1. ✅ Install Loki stack (Loki + Promtail)
2. ✅ Verify logs from all pods are being collected
3. ✅ Create log-based alerts (error rate spike)
4. ✅ Add log panels to existing dashboards

**Expected result:** Centralized log search across all services

### **Phase 4: Custom Dashboards (Week 4)**
1. ✅ Create June Platform Overview dashboard
2. ✅ Create June Dark OSINT Pipeline dashboard
3. ✅ Create Media Stack Health dashboard
4. ✅ Fine-tune alert thresholds based on real data

**Expected result:** Complete visibility into all systems

### **Phase 5: Advanced Features (Optional)**
1. ⭐ Add Grafana Tempo for distributed tracing
2. ⭐ Set up Grafana OnCall for incident management
3. ⭐ Configure remote write from TTS/STT services
4. ⭐ Add custom metrics to your applications

---

## Alternative: Lightweight Stack (Budget Option)

If resources are constrained, use **VictoriaMetrics** instead of Prometheus:

**Benefits:**
- 10x less memory usage than Prometheus
- 10x less storage usage (better compression)
- Drop-in replacement (compatible with Prometheus)

**Trade-offs:**
- Less mature ecosystem
- Fewer pre-built integrations

```bash
# Install victoria-metrics-k8s-stack instead
helm install victoria-metrics vm/victoria-metrics-k8s-stack \
  --namespace monitoring \
  --values victoria-metrics-values.yaml
```

---

## Next Steps

**I can help you with:**

1. **Generate Helm values files** for kube-prometheus-stack and Loki
2. **Create custom Grafana dashboards** for June Platform, June Dark, Media Stack
3. **Write alert rules** specific to your services
4. **Set up ServiceMonitors** to scrape your application metrics
5. **Configure remote write** from TTS/STT services
6. **Deploy the entire stack** with optimized settings for your cluster

**Would you like me to:**
- A) **Deploy the full stack now** (kube-prometheus-stack + Loki)
- B) **Start with Phase 1** (just Prometheus + Grafana for cluster monitoring)
- C) **Create the Helm values files** for you to review before deployment
- D) **Design custom dashboards** for your specific services first

**Recommendation:** Start with **Option C** - I'll generate all the configuration files, you review them, then we deploy together. This gives you full control and understanding of what's being deployed.

What would you like to do?
