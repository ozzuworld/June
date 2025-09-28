# Harbor Registry Module

This Terraform module deploys Harbor container registry on Google Kubernetes Engine (GKE) with a single pod configuration for minimal resource usage.

## Features

- **Single Pod Deployment**: Optimized for development and testing environments with minimal resource requirements
- **GKE Integration**: Native integration with Google Kubernetes Engine
- **Persistent Storage**: Configurable persistent volumes for registry data, database, and Redis
- **Security**: Built-in security context and RBAC configuration
- **Optional Components**: Enable/disable Trivy vulnerability scanning and metrics collection
- **Flexible Networking**: Support for both ClusterIP (internal) and Ingress (external) access
- **Terraform Best Practices**: Follows Terraform best practices with proper variable validation

## Architecture

This module deploys Harbor with the following components:

- **Harbor Core**: Main API server (1 replica)
- **Harbor Portal**: Web UI (1 replica)
- **Harbor Registry**: Docker registry backend (1 replica)
- **Harbor Job Service**: Handles asynchronous jobs (1 replica)
- **PostgreSQL**: Internal database (1 replica)
- **Redis**: Internal cache and job queue (1 replica)
- **Trivy**: Vulnerability scanner (optional, 1 replica)

## Prerequisites

- GKE cluster with Kubernetes 1.20+
- Helm 3.2.0+
- Terraform 1.0+
- `kubectl` configured to access your GKE cluster

## Usage

### Basic Usage

```hcl
module "harbor_registry" {
  source = "./modules/harbor-registry"
  
  # Required variables
  project_id       = "your-gcp-project"
  cluster_name     = "your-gke-cluster"
  cluster_location = "us-central1"
  
  # Harbor configuration
  harbor_admin_password = "SecurePassword123!"
  harbor_external_url   = "http://harbor.your-domain.com"
  harbor_hostname       = "harbor.your-domain.com"
  
  # Storage configuration
  registry_storage_size  = "50Gi"
  database_storage_size  = "10Gi"
  redis_storage_size     = "5Gi"
  storage_class         = "standard-rwo"
  
  # Optional features
  enable_trivy_scanning = true
  enable_metrics       = false
  create_ingress       = false
  
  labels = {
    environment = "development"
    project     = "june-ai-platform"
    managed_by  = "terraform"
  }
}
```

### With Ingress and TLS

```hcl
module "harbor_registry" {
  source = "./modules/harbor-registry"
  
  # ... basic configuration ...
  
  # Enable external access
  create_ingress = true
  enable_tls     = true
  tls_secret_name = "harbor-tls-cert"
  static_ip_name  = "harbor-static-ip"
  
  ingress_annotations = {
    "cert-manager.io/cluster-issuer" = "letsencrypt-prod"
    "kubernetes.io/ingress.class"    = "gce"
  }
}
```

### Production Configuration

```hcl
module "harbor_registry" {
  source = "./modules/harbor-registry"
  
  # ... basic configuration ...
  
  # Production storage sizes
  registry_storage_size = "500Gi"
  database_storage_size = "50Gi"
  redis_storage_size    = "20Gi"
  storage_class        = "ssd"
  
  # Enable all features
  enable_trivy_scanning = true
  enable_metrics       = true
  create_ingress       = true
  enable_tls          = true
  
  # Node placement
  node_selector = {
    "cloud.google.com/gke-nodepool" = "harbor-pool"
  }
  
  tolerations = [
    {
      key      = "harbor"
      operator = "Equal"
      value    = "true"
      effect   = "NoSchedule"
    }
  ]
}
```

## Integration with Main Terraform Configuration

Add this to your main `main.tf`:

```hcl
# Add to main.tf in infrastructure/terraform/

# Create GKE cluster first (if not already created)
data "google_container_cluster" "june_cluster" {
  name     = var.cluster_name
  location = var.region
  project  = var.project_id
}

# Configure Kubernetes and Helm providers
provider "kubernetes" {
  host  = "https://${data.google_container_cluster.june_cluster.endpoint}"
  token = data.google_client_config.default.access_token
  cluster_ca_certificate = base64decode(
    data.google_container_cluster.june_cluster.master_auth[0].cluster_ca_certificate
  )
}

provider "helm" {
  kubernetes {
    host  = "https://${data.google_container_cluster.june_cluster.endpoint}"
    token = data.google_client_config.default.access_token
    cluster_ca_certificate = base64decode(
      data.google_container_cluster.june_cluster.master_auth[0].cluster_ca_certificate
    )
  }
}

data "google_client_config" "default" {}

# Deploy Harbor Registry
module "harbor_registry" {
  source = "./modules/harbor-registry"
  
  project_id       = var.project_id
  cluster_name     = var.cluster_name
  cluster_location = var.region
  
  harbor_admin_password = var.harbor_admin_password
  harbor_external_url   = "http://harbor.${var.domain_name}"
  harbor_hostname       = "harbor.${var.domain_name}"
  
  labels = local.common_labels
}
```

Add these variables to your `variables.tf`:

```hcl
variable "harbor_admin_password" {
  description = "Harbor administrator password"
  type        = string
  sensitive   = true
}

variable "domain_name" {
  description = "Base domain name for services"
  type        = string
  default     = "june-ai.local"
}

variable "cluster_name" {
  description = "Name of the GKE cluster"
  type        = string
  default     = "june-cluster"
}
```

## Accessing Harbor

### Internal Access (ClusterIP)

```bash
# Port forward to access Harbor locally
kubectl port-forward -n harbor-system svc/harbor 8080:80

# Access Harbor at http://localhost:8080
# Username: admin
# Password: [your-harbor-admin-password]
```

### External Access (Ingress)

If ingress is enabled, access Harbor at: `https://harbor.your-domain.com`

### Using Harbor as Docker Registry

```bash
# Log in to Harbor
docker login harbor.your-domain.com
# Username: admin
# Password: [your-harbor-admin-password]

# Tag and push an image
docker tag my-app:latest harbor.your-domain.com/june/my-app:latest
docker push harbor.your-domain.com/june/my-app:latest

# Pull an image
docker pull harbor.your-domain.com/june/my-app:latest
```

## Monitoring and Maintenance

### Useful Commands

The module outputs provide helpful kubectl commands:

```bash
# View all Harbor pods
kubectl get pods -n harbor-system

# Check Harbor services
kubectl get services -n harbor-system

# View persistent volume claims
kubectl get pvc -n harbor-system

# Check Harbor core logs
kubectl logs -n harbor-system -l app=harbor,component=core

# Check Harbor registry logs
kubectl logs -n harbor-system -l app=harbor,component=registry
```

### Storage Management

```bash
# Check storage usage
kubectl exec -n harbor-system -it <harbor-core-pod> -- df -h

# View PV status
kubectl get pv | grep harbor
```

### Backup Considerations

- **Database**: Backup PostgreSQL data regularly
- **Registry Images**: Consider using external object storage (GCS) for production
- **Configuration**: Export Harbor configuration through the API

## Troubleshooting

### Common Issues

1. **Pod Stuck in Pending**: Check storage class availability and node resources
2. **Database Connection Issues**: Verify PostgreSQL pod is running and healthy
3. **Image Push/Pull Failures**: Check Harbor core service and ingress configuration
4. **Storage Issues**: Verify persistent volumes are properly bound

### Debug Commands

```bash
# Check Helm release status
helm status harbor -n harbor-system

# View Harbor deployment events
kubectl get events -n harbor-system --sort-by='.lastTimestamp'

# Check resource usage
kubectl top pods -n harbor-system

# Describe problematic pods
kubectl describe pod <pod-name> -n harbor-system
```

## Security Considerations

- **Admin Password**: Use a strong password and store it securely
- **Network Policies**: Consider implementing Kubernetes Network Policies
- **RBAC**: Review and customize service account permissions as needed
- **TLS**: Always use HTTPS/TLS in production environments
- **Vulnerability Scanning**: Enable Trivy for container image vulnerability scanning

## Resource Requirements

### Minimum Resources (Single Pod Config)

- **CPU**: ~0.5 cores total
- **Memory**: ~2-3 GB total
- **Storage**: ~20 GB minimum (configurable)

### Recommended Resources

- **CPU**: 1-2 cores
- **Memory**: 4-6 GB
- **Storage**: 100+ GB for registry data

## Limitations

- **Single Pod**: Not suitable for high availability requirements
- **Performance**: Limited by single replica configuration
- **Scalability**: Does not auto-scale based on load

For production high-availability deployments, consider using multiple replicas and external databases/Redis clusters.

## Contributing

When modifying this module:

1. Update variable validation rules as needed
2. Test with different GKE cluster configurations
3. Update documentation for any new features
4. Follow Terraform best practices
5. Test both minimal and full-featured deployments