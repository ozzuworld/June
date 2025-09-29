Here's a README that is clear, concise, and gives full context to any AI or human operator about the purpose, architecture, and operational approach of June Dark and the supporting control plane infrastructure on Kubernetes.

June Dark OSINT Framework and Control Plane Deployment
Project Purpose
June Dark is an advanced Open Source Intelligence (OSINT) platform combining computer vision, threat intelligence, and orchestration. It's designed to process and correlate visual/media data with cyber intelligence, but all heavy computation (AI, vision, ML) is offloaded to dedicated external machines.

The Kubernetes cluster serves as the admin, monitoring, database, coordination, and web UI layer for up to 3 users.
Heavy tasks are dispatched from this control plane to GPU-powered servers, with results returned via REST API and RabbitMQ.

High-Level Architecture
Component	Cluster Role	Resources (in-cluster)	Offloaded to external
OpenCTI Platform	Threat intel, admin, API	1GB RAM, 0.3 CPU	No
June Orchestrator	Coordination/queue/admin	512Mi RAM, 0.2 CPU	No
June IDP	Identity/Auth	256Mi RAM, 0.2 CPU	No
PostgreSQL	Metadata, configs	512Mi RAM, 0.1 CPU	No
Elasticsearch	Search, index, dashboard	1GB RAM, 0.3 CPU	No
RabbitMQ	Queue dispatch (AI/vision jobs)	256Mi RAM, 0.1 CPU	Yes
Redis	Session, cache	256Mi RAM, 0.1 CPU	No
MinIO	Artifact, result storage	128Mi RAM, 0.1 CPU	Yes
Monitoring stack	Prometheus/Grafana (optional)	256Mi RAM, 0.1 CPU each	No
June Dark OSINT	Heavy GPU/AI analysis	none (EXTERNAL, off-cluster)	Yes
Key Design: Control Plane vs. Worker Layer
K8s Cluster: Only runs admin services, UI, queue, artifact storage, and databases with minimal resource needs.

Vision/AI and ML: All detection and analysis (YOLO, embedding, etc.) are run on powerful baremetal/VMs external to cluster.

RabbitMQ: Central coordination - June Dark (external) polls jobs, processes, and sends results via MinIO/REST/Rabbit.

Interaction Pattern
User/Analyst interacts with UI/API → (on cluster)

Task queued in RabbitMQ

External Worker (June Dark) takes job:

Pulls image/artifact from MinIO/S3 or database via REST

Runs vision/AI (YOLO, OCR, audio, etc.)

Posts results back to OpenCTI/Elasticsearch for reporting

Notifies via REST or queue callback

Resource Optimization
All microservices (<1GB RAM, <0.3 CPU, 1 pod/replica each)

Shared queues/cache/database

Elasticsearch JVM heap: 512Mi to 1Gi

MinIO: Dedicated bucket for artifacts, limit retention

All admin/monitoring is low-frequency, suitable for 1–3 users only

PVCs and storage class set for free tier GKE quotas

Off-Cluster/External Worker Example
python
# External Worker - how real June Dark GPU processing happens in practice
import pika, requests
def worker_loop():
    rabbit = pika.BlockingConnection(pika.URLParameters('amqp://user:pass@rabbit.yourcluster:5672/'))
    # poll queue, download artifact from MinIO or REST
    # process AI/vision work on local GPU
    # upload results, POST to cluster API for reporting/storage
Quickstart
Deploy Control Plane
bash
kubectl apply -f infrastructure/kubernetes/opencti-micro/
kubectl apply -f infrastructure/kubernetes/june-orchestrator-micro.yaml
kubectl apply -f infrastructure/kubernetes/june-idp-micro.yaml
# ... and supporting databases/queues/storage
Deploy External Workers
Spin up powerful machines externally.
Configure connection to cluster RabbitMQ, MinIO, REST API endpoints.
Keep credentials/secrets in .env and k8s Secrets.

Maintenance/Scaling
Scale up cluster if user count or admin workload increases.

Offload more tasks to external workers as data volume grows.

Watch for cluster resource exhaustion especially if adding more users or concurrent reporting.

Security
All secrets/credentials managed in k8s Secrets, IAM

Network restricted by namespace and NetworkPolicy

Data at rest: MinIO S3 bucket encryption enabled, KMS integration possible

All external traffic over HTTPS, tokens (JWT) for worker API access

Useful Endpoints
Service	Endpoint
OpenCTI API	/api/
June Orchestrator	/v1/chat /health /metrics
MinIO S3	/minio/
RabbitMQ	/amqp/ queue interface
Grafana/Prometheus	/grafana/ /prometheus/
Summary
June Dark (external) is the heavy OSINT/AI engine.
The cluster is its admin/dashboard/queue/data backbone.
You get full functionality and reporting for a small group,
but offload all compute and AI expenses to dedicated external machines.

I will update the current README at ozzuworld/june/june/services/june-dark/README.md to reflect this model, and document the infrastructure plan for K8s in detail as shown above.

cat > June/services/june-dark/README.md <<'EOF'
# June Dark OSINT Framework - Control Plane Architecture

## **Project Overview**

June Dark is a distributed OSINT (Open Source Intelligence) platform where the **Kubernetes cluster serves as the control plane** (admin, coordination, storage, queuing) and **heavy AI/ML processing is offloaded to external powerful machines**.

### **Architecture Philosophy**
- **K8s Cluster**: Admin UI, APIs, databases, queues, coordination (lightweight)
- **External Workers**: GPU-intensive YOLO, speech processing, computer vision (heavy)
- **Communication**: RabbitMQ queues + REST APIs + MinIO artifact storage

## **Current Deployment Model**

### **Control Plane Services (On K8s Cluster)**
| Service | Purpose | Resources | Replicas |
|---------|---------|-----------|----------|
| OpenCTI Platform | Threat intelligence UI/API | 1GB RAM, 0.4 CPU | 1 |
| June Orchestrator | Coordination API | 512Mi RAM, 0.2 CPU | 1 |
| June IDP | Authentication | 256Mi RAM, 0.1 CPU | 1 |
| Elasticsearch | Search/indexing only | 512Mi RAM, 0.2 CPU | 1 |
| PostgreSQL | Metadata storage | 256Mi RAM, 0.1 CPU | 1 |
| Redis | Session/cache | 128Mi RAM, 0.1 CPU | 1 |
| RabbitMQ | Task queuing | 256Mi RAM, 0.1 CPU | 1 |
| MinIO | Artifact storage | 128Mi RAM, 0.1 CPU | 1 |

**Total Cluster Usage**: ~3GB RAM, 1.5 CPU cores

### **External Worker Services (Off K8s Cluster)**
| Service | Purpose | Location | Resources |
|---------|---------|-----------|-----------|
| June Dark OSINT | YOLOv11, computer vision | Powerful GPU server | 8GB+ VRAM, 4+ CPU |
| June STT | Speech-to-text | Powerful CPU/GPU server | 4GB+ RAM, GPU optional |
| June TTS | Text-to-speech | Powerful CPU/GPU server | 4GB+ RAM, GPU optional |

## **Cluster Resource Optimization**

### **Current Cluster Constraints**
- **Node Pool**: 2x e2-standard-2 (2 vCPU, 8GB RAM each)
- **Total Available**: ~3.8 CPU cores, 11.6GB RAM
- **User Limit**: Maximum 3 concurrent users
- **Usage Pattern**: Admin/monitoring/coordination only

### **Resource Allocation Strategy**
