# Harbor Registry Module - Single Pod Configuration for GKE
# This module deploys Harbor container registry using Helm on GKE

terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.11"
    }
  }
}

# Create Harbor namespace
resource "kubernetes_namespace" "harbor" {
  metadata {
    name = var.harbor_namespace
    labels = merge(var.labels, {
      "app.kubernetes.io/name" = "harbor"
    })
  }
}

# Create Harbor admin secret
resource "kubernetes_secret" "harbor_admin" {
  metadata {
    name      = "harbor-admin-secret"
    namespace = kubernetes_namespace.harbor.metadata[0].name
    labels    = var.labels
  }
  
  data = {
    HARBOR_ADMIN_PASSWORD = var.harbor_admin_password
  }
  
  type = "Opaque"
}

# Harbor Helm Chart Deployment
resource "helm_release" "harbor" {
  name       = "harbor"
  namespace  = kubernetes_namespace.harbor.metadata[0].name
  repository = "https://helm.goharbor.io"
  chart      = "harbor"
  version    = var.harbor_chart_version
  
  # Wait for deployment to be ready
  wait          = true
  wait_for_jobs = true
  timeout       = 600

  values = [
    yamlencode({
      # External URL configuration
      externalURL = var.harbor_external_url
      
      # Disable HTTPS if using internal cluster setup
      expose = {
        type = "clusterIP"
        tls = {
          enabled = false
        }
        clusterIP = {
          name = "harbor"
          ports = {
            httpPort = 80
          }
        }
      }

      # Single replica configuration for minimal deployment
      portal = {
        replicas = 1
        resources = {
          requests = {
            cpu    = "100m"
            memory = "256Mi"
          }
          limits = {
            cpu    = "500m"
            memory = "512Mi"
          }
        }
      }
      
      core = {
        replicas = 1
        resources = {
          requests = {
            cpu    = "100m"
            memory = "512Mi"
          }
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
      
      jobservice = {
        replicas = 1
        resources = {
          requests = {
            cpu    = "100m"
            memory = "256Mi"
          }
          limits = {
            cpu    = "500m"
            memory = "512Mi"
          }
        }
      }
      
      registry = {
        replicas = 1
        resources = {
          requests = {
            cpu    = "100m"
            memory = "256Mi"
          }
          limits = {
            cpu    = "500m"
            memory = "512Mi"
          }
        }
      }

      # Use internal components (single pod setup)
      database = {
        type = "internal"
        internal = {
          resources = {
            requests = {
              cpu    = "100m"
              memory = "256Mi"
            }
            limits = {
              cpu    = "500m"
              memory = "1Gi"
            }
          }
        }
      }
      
      redis = {
        type = "internal"
        internal = {
          resources = {
            requests = {
              cpu    = "100m"
              memory = "256Mi"
            }
            limits = {
              cpu    = "500m"
              memory = "512Mi"
            }
          }
        }
      }

      # Disable non-essential services for minimal deployment
      notary = {
        enabled = false
      }
      
      trivy = {
        enabled = var.enable_trivy_scanning
        replicas = var.enable_trivy_scanning ? 1 : 0
        resources = var.enable_trivy_scanning ? {
          requests = {
            cpu    = "100m"
            memory = "512Mi"
          }
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        } : {}
      }

      # Metrics and monitoring
      metrics = {
        enabled = var.enable_metrics
        serviceMonitor = {
          enabled = var.enable_metrics
        }
      }

      # Persistence configuration
      persistence = {
        enabled = true
        resourcePolicy = "keep"
        persistentVolumeClaim = {
          registry = {
            size         = var.registry_storage_size
            storageClass = var.storage_class
            accessMode   = "ReadWriteOnce"
          }
          database = {
            size         = var.database_storage_size
            storageClass = var.storage_class
            accessMode   = "ReadWriteOnce"
          }
          redis = {
            size         = var.redis_storage_size
            storageClass = var.storage_class
            accessMode   = "ReadWriteOnce"
          }
        }
      }

      # Harbor admin password from secret
      existingSecretAdminPassword    = kubernetes_secret.harbor_admin.metadata[0].name
      existingSecretAdminPasswordKey = "HARBOR_ADMIN_PASSWORD"

      # Security context
      securityContext = {
        runAsNonRoot = true
        runAsUser    = 10000
        fsGroup      = 10000
      }

      # Node selector for GKE
      nodeSelector = var.node_selector

      # Tolerations if needed
      tolerations = var.tolerations

      # Pod disruption budget for single pod (minimal)
      podDisruptionBudget = {
        maxUnavailable = 1
      }
    })
  ]

  depends_on = [
    kubernetes_namespace.harbor,
    kubernetes_secret.harbor_admin
  ]
}

# Create a service to access Harbor internally
resource "kubernetes_service" "harbor_internal" {
  count = var.create_internal_service ? 1 : 0
  
  metadata {
    name      = "harbor-internal"
    namespace = kubernetes_namespace.harbor.metadata[0].name
    labels    = merge(var.labels, {
      "app.kubernetes.io/name"      = "harbor"
      "app.kubernetes.io/component" = "portal"
    })
  }
  
  spec {
    selector = {
      "app" = "harbor"
      "component" = "portal"
    }
    
    port {
      name        = "http"
      port        = 80
      target_port = 8080
      protocol    = "TCP"
    }
    
    type = "ClusterIP"
  }
  
  depends_on = [helm_release.harbor]
}

# Optional: Create ingress for external access
resource "kubernetes_ingress_v1" "harbor_ingress" {
  count = var.create_ingress ? 1 : 0
  
  metadata {
    name      = "harbor-ingress"
    namespace = kubernetes_namespace.harbor.metadata[0].name
    labels    = var.labels
    annotations = merge(
      var.ingress_annotations,
      {
        "kubernetes.io/ingress.class"                = "gce"
        "kubernetes.io/ingress.global-static-ip-name" = var.static_ip_name
      }
    )
  }
  
  spec {
    rule {
      host = var.harbor_hostname
      http {
        path {
          path      = "/"
          path_type = "Prefix"
          backend {
            service {
              name = helm_release.harbor.name
              port {
                number = 80
              }
            }
          }
        }
      }
    }
    
    dynamic "tls" {
      for_each = var.enable_tls ? [1] : []
      content {
        hosts       = [var.harbor_hostname]
        secret_name = var.tls_secret_name
      }
    }
  }
  
  depends_on = [helm_release.harbor]
}