# infra/gke/enhanced-main.tf - Complete Terraform with Oracle and Keycloak deployment

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = "~> 1.14"
    }
  }
}

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "cluster_name" {
  description = "GKE cluster name"
  type        = string
  default     = "june-unified-cluster"
}

# Oracle wallet files (base64 encoded)
variable "oracle_cwallet_sso" {
  description = "Oracle cwallet.sso file (base64 encoded)"
  type        = string
  sensitive   = true
}

variable "oracle_ewallet_p12" {
  description = "Oracle ewallet.p12 file (base64 encoded)"
  type        = string
  sensitive   = true
}

variable "oracle_tnsnames_ora" {
  description = "Oracle tnsnames.ora file (base64 encoded)"
  type        = string
  sensitive   = true
}

variable "oracle_sqlnet_ora" {
  description = "Oracle sqlnet.ora file (base64 encoded)"
  type        = string
  sensitive   = true
}

# Database passwords
variable "harbor_db_password" {
  description = "Harbor database password"
  type        = string
  sensitive   = true
  default     = "HarborPass123!@#"
}

variable "keycloak_db_password" {
  description = "Keycloak database password"
  type        = string
  sensitive   = true
  default     = "KeycloakPass123!@#"
}

# Enable required APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "container.googleapis.com",
    "compute.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com"
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# VPC and Subnet for GKE
resource "google_compute_network" "main" {
  name                    = "${var.cluster_name}-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "main" {
  name                     = "${var.cluster_name}-subnet"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.main.id
  ip_cidr_range            = "10.0.0.0/16"
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "${var.cluster_name}-pods"
    ip_cidr_range = "10.4.0.0/14"
  }

  secondary_ip_range {
    range_name    = "${var.cluster_name}-services"
    ip_cidr_range = "10.8.0.0/20"
  }
}

# GKE Autopilot Cluster
resource "google_container_cluster" "cluster" {
  name     = var.cluster_name
  location = var.region
  project  = var.project_id

  enable_autopilot = true

  network    = google_compute_network.main.id
  subnetwork = google_compute_subnetwork.main.name

  ip_allocation_policy {
    cluster_secondary_range_name  = google_compute_subnetwork.main.secondary_ip_range[0].range_name
    services_secondary_range_name = google_compute_subnetwork.main.secondary_ip_range[1].range_name
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  depends_on = [google_project_service.apis]
}

# Service accounts for workload identity
resource "google_service_account" "workload_identity" {
  for_each = toset([
    "harbor",
    "june-orchestrator",
    "june-stt", 
    "june-tts",
    "june-idp"
  ])
  
  account_id   = "${each.key}-gke"
  display_name = "${each.key} GKE Service Account"
  project      = var.project_id
}

# Basic IAM permissions
resource "google_project_iam_member" "workload_permissions" {
  for_each = {
    "harbor-storage" = {
      sa   = "harbor"
      role = "roles/storage.admin"
    }
    "orchestrator-monitoring" = {
      sa   = "june-orchestrator"
      role = "roles/monitoring.metricWriter"
    }
    "stt-monitoring" = {
      sa   = "june-stt"
      role = "roles/monitoring.metricWriter"
    }
    "tts-monitoring" = {
      sa   = "june-tts"
      role = "roles/monitoring.metricWriter"
    }
    "idp-monitoring" = {
      sa   = "june-idp"
      role = "roles/monitoring.metricWriter"
    }
  }
  
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.workload_identity[each.value.sa].email}"
}

# Artifact Registry for container images
resource "google_artifact_registry_repository" "june_repo" {
  location      = var.region
  project       = var.project_id
  repository_id = "june"
  description   = "June AI Platform container registry"
  format        = "DOCKER"
}

# Global static IP for ingress
resource "google_compute_global_address" "june_ip" {
  name    = "june-services-ip"
  project = var.project_id
}

# Storage bucket for Harbor registry storage
resource "google_storage_bucket" "harbor_registry" {
  name     = "${var.project_id}-harbor-registry"
  location = var.region
  project  = var.project_id

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  
  versioning {
    enabled = true
  }
  
  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}

# Kubernetes provider configuration
data "google_client_config" "provider" {}

provider "kubernetes" {
  host  = "https://${google_container_cluster.cluster.endpoint}"
  token = data.google_client_config.provider.access_token
  cluster_ca_certificate = base64decode(
    google_container_cluster.cluster.master_auth[0].cluster_ca_certificate,
  )
}

provider "kubectl" {
  host  = "https://${google_container_cluster.cluster.endpoint}"
  token = data.google_client_config.provider.access_token
  cluster_ca_certificate = base64decode(
    google_container_cluster.cluster.master_auth[0].cluster_ca_certificate,
  )
  load_config_file = false
}

# Create namespaces
resource "kubernetes_namespace" "namespaces" {
  for_each = toset([
    "harbor",
    "june-services"
  ])
  
  metadata {
    name = each.key
    labels = {
      managed-by = "terraform"
      purpose    = "june-platform"
    }
  }
  
  depends_on = [google_container_cluster.cluster]
}

# Service accounts with Workload Identity annotations
resource "kubernetes_service_account" "workload_identity_sa" {
  for_each = {
    "harbor"             = "harbor"
    "june-orchestrator"  = "june-services" 
    "june-stt"          = "june-services"
    "june-tts"          = "june-services"
    "june-idp"          = "june-services"
  }
  
  metadata {
    name      = each.key
    namespace = each.value
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.workload_identity[each.key].email
    }
    labels = {
      managed-by = "terraform"
      service    = each.key
    }
  }
  
  depends_on = [kubernetes_namespace.namespaces]
}

# Workload Identity bindings
resource "google_service_account_iam_member" "workload_identity_binding" {
  for_each = toset([
    "harbor",
    "june-orchestrator",
    "june-stt", 
    "june-tts",
    "june-idp"
  ])
  
  service_account_id = google_service_account.workload_identity[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${each.key == "harbor" ? "harbor" : "june-services"}/${each.key}]"
}

# Oracle wallet secrets
resource "kubernetes_secret" "oracle_wallet" {
  for_each = toset(["harbor", "june-services"])
  
  metadata {
    name      = "oracle-wallet"
    namespace = each.key
    labels = {
      managed-by = "terraform"
    }
  }

  data = {
    "cwallet.sso"   = var.oracle_cwallet_sso
    "ewallet.p12"   = var.oracle_ewallet_p12
    "tnsnames.ora"  = var.oracle_tnsnames_ora
    "sqlnet.ora"    = var.oracle_sqlnet_ora
  }

  type = "Opaque"
  
  depends_on = [kubernetes_namespace.namespaces]
}

# Oracle database credentials
resource "kubernetes_secret" "oracle_credentials" {
  for_each = {
    "harbor" = {
      namespace = "harbor"
      host      = "adb.us-ashburn-1.oraclecloud.com"
      service   = "ga342747dd21cdf_harbordb_high.adb.oraclecloud.com"
      user      = "harbor_user"
      password  = var.harbor_db_password
    }
    "june-services" = {
      namespace = "june-services"
      host      = "adb.us-ashburn-1.oraclecloud.com"
      service   = "ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com"
      user      = "keycloak_user"
      password  = var.keycloak_db_password
    }
  }
  
  metadata {
    name      = "oracle-credentials"
    namespace = each.value.namespace
    labels = {
      managed-by = "terraform"
    }
  }

  data = {
    DB_HOST     = each.value.host
    DB_PORT     = "1522"
    DB_SERVICE  = each.value.service
    DB_USER     = each.value.user
    DB_PASSWORD = each.value.password
  }

  type = "Opaque"
  
  depends_on = [kubernetes_namespace.namespaces]
}

# Generate secure secrets for services
resource "random_password" "service_secrets" {
  for_each = toset([
    "orchestrator",
    "stt",
    "tts"
  ])
  
  length  = 32
  special = true
}

# Application secrets
resource "kubernetes_secret" "june_secrets" {
  metadata {
    name      = "june-secrets"
    namespace = "june-services"
    labels = {
      managed-by = "terraform"
    }
  }

  data = {
    ORCHESTRATOR_CLIENT_ID     = "orchestrator-client"
    ORCHESTRATOR_CLIENT_SECRET = random_password.service_secrets["orchestrator"].result
    STT_CLIENT_ID              = "stt-client"
    STT_CLIENT_SECRET          = random_password.service_secrets["stt"].result
    TTS_CLIENT_ID              = "tts-client"
    TTS_CLIENT_SECRET          = random_password.service_secrets["tts"].result
    GEMINI_API_KEY             = ""  # Set via tfvars
    CHATTERBOX_API_KEY         = ""  # Set via tfvars
  }

  type = "Opaque"
  
  depends_on = [kubernetes_namespace.namespaces]
}

# Keycloak ConfigMap
resource "kubernetes_config_map" "keycloak_config" {
  metadata {
    name      = "keycloak-config"
    namespace = "june-services"
    labels = {
      managed-by = "terraform"
    }
  }

  data = {
    KC_DB                      = "oracle"
    KC_DB_URL                  = "jdbc:oracle:thin:@tcps://adb.us-ashburn-1.oraclecloud.com:1522/ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com?wallet_location=/opt/oracle/wallet"
    KC_DB_USERNAME             = "keycloak_user"
    KC_HOSTNAME_STRICT         = "false"
    KC_HTTP_ENABLED            = "true"
    KC_HEALTH_ENABLED          = "true"
    KC_METRICS_ENABLED         = "true"
    KC_TRANSACTION_XA_ENABLED  = "false"
    KC_CACHE                   = "local"
    KC_LOG_LEVEL               = "INFO"
    KC_PROXY                   = "edge"
    TNS_ADMIN                  = "/opt/oracle/wallet"
    ORACLE_HOME                = "/opt/oracle"
    JAVA_OPTS_APPEND           = "-XX:MaxRAMPercentage=70.0 -XX:+UseContainerSupport"
  }
  
  depends_on = [kubernetes_namespace.namespaces]
}

# Keycloak secrets
resource "kubernetes_secret" "keycloak_secrets" {
  metadata {
    name      = "keycloak-secrets"
    namespace = "june-services"
    labels = {
      managed-by = "terraform"
    }
  }

  data = {
    KC_DB_PASSWORD         = var.keycloak_db_password
    KEYCLOAK_ADMIN         = "admin"
    KEYCLOAK_ADMIN_PASSWORD = "admin123456"
  }

  type = "Opaque"
  
  depends_on = [kubernetes_namespace.namespaces]
}

# Keycloak Deployment
resource "kubectl_manifest" "keycloak_deployment" {
  yaml_body = <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-idp
  namespace: june-services
  labels:
    app: june-idp
    managed-by: terraform
spec:
  replicas: 1
  selector:
    matchLabels:
      app: june-idp
  template:
    metadata:
      labels:
        app: june-idp
    spec:
      serviceAccountName: june-idp
      securityContext:
        fsGroup: 1000
      
      initContainers:
      - name: setup-oracle-wallet
        image: oraclelinux:8-slim
        command: ['sh', '-c', 'chmod 644 /opt/oracle/wallet/* && ls -la /opt/oracle/wallet/']
        volumeMounts:
        - name: oracle-wallet
          mountPath: /opt/oracle/wallet
        resources:
          requests:
            memory: "64Mi"
            cpu: "50m"
          limits:
            memory: "128Mi"
            cpu: "100m"
      
      - name: wait-for-oracle
        image: busybox:1.35
        command: ['sh', '-c']
        args:
          - |
            i=0
            until nc -z adb.us-ashburn-1.oraclecloud.com 1522; do
              echo "Waiting for Oracle... (attempt $((++i)))"
              sleep 10
              if [ $i -gt 30 ]; then
                echo "Timeout waiting for Oracle"
                exit 1
              fi
            done
            echo "Oracle is reachable!"
        resources:
          requests:
            memory: "32Mi"
            cpu: "25m"
          limits:
            memory: "64Mi"
            cpu: "50m"
      
      containers:
      - name: keycloak
        image: quay.io/keycloak/keycloak:23.0.0
        args:
          - "start"
          - "--db=oracle"
          - "--http-enabled=true"
          - "--hostname-strict=false"
          - "--proxy=edge"
          - "--transaction-xa-enabled=false"
          - "--cache=local"
          - "--health-enabled=true"
          - "--metrics-enabled=true"
        
        ports:
        - name: http
          containerPort: 8080
        
        envFrom:
        - configMapRef:
            name: keycloak-config
        
        env:
        - name: KC_DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: keycloak-secrets
              key: KC_DB_PASSWORD
        - name: KEYCLOAK_ADMIN
          valueFrom:
            secretKeyRef:
              name: keycloak-secrets
              key: KEYCLOAK_ADMIN
        - name: KEYCLOAK_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: keycloak-secrets
              key: KEYCLOAK_ADMIN_PASSWORD
        
        volumeMounts:
        - name: oracle-wallet
          mountPath: /opt/oracle/wallet
          readOnly: true
        
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 120
          periodSeconds: 30
          timeoutSeconds: 10
          failureThreshold: 5
        
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 60
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 10
        
        startupProbe:
          httpGet:
            path: /health/started
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 15
          timeoutSeconds: 10
          failureThreshold: 40
      
      volumes:
      - name: oracle-wallet
        secret:
          secretName: oracle-wallet
          defaultMode: 0644
YAML
  
  depends_on = [
    kubernetes_secret.oracle_wallet,
    kubernetes_secret.keycloak_secrets,
    kubernetes_config_map.keycloak_config,
    kubernetes_service_account.workload_identity_sa
  ]
}

# Keycloak Service
resource "kubernetes_service" "keycloak_service" {
  metadata {
    name      = "june-idp"
    namespace = "june-services"
    labels = {
      app        = "june-idp"
      managed-by = "terraform"
    }
  }

  spec {
    type = "ClusterIP"
    
    port {
      port        = 8080
      target_port = 8080
    }
    
    selector = {
      app = "june-idp"
    }
  }
  
  depends_on = [kubernetes_namespace.namespaces]
}

# Outputs
output "cluster_name" {
  description = "GKE cluster name"
  value       = google_container_cluster.cluster.name
}

output "cluster_endpoint" {
  description = "GKE cluster endpoint"
  value       = google_container_cluster.cluster.endpoint
  sensitive   = true
}

output "get_credentials_command" {
  description = "Command to configure kubectl"
  value       = "gcloud container clusters get-credentials ${google_container_cluster.cluster.name} --region=${var.region} --project=${var.project_id}"
}

output "artifact_registry_url" {
  description = "Artifact Registry URL"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/june"
}

output "static_ip" {
  description = "Static IP for ingress"
  value       = google_compute_global_address.june_ip.address
}

output "harbor_bucket" {
  description = "Harbor storage bucket"
  value       = google_storage_bucket.harbor_registry.name
}

output "keycloak_admin_url" {
  description = "Keycloak admin URL (use with port-forward)"
  value       = "kubectl port-forward -n june-services svc/june-idp 8080:8080"
}

output "service_account_emails" {
  description = "Service account emails for workload identity"
  value = {
    for k, v in google_service_account.workload_identity : k => v.email
  }
}