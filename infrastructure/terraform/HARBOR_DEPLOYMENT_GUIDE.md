# Harbor Registry Deployment Guide

This guide will help you deploy Harbor container registry on your GKE cluster using Terraform.

## Prerequisites

### 1. Required Tools

Ensure you have the following tools installed:

```bash
# Check Terraform version (>= 1.0)
terraform version

# Check kubectl
kubectl version --client

# Check Helm (>= 3.2.0)
helm version

# Check gcloud CLI
gcloud version
```

### 2. GCP Authentication

```bash
# Authenticate with GCP
gcloud auth login
gcloud auth application-default login

# Set your project
gcloud config set project YOUR_PROJECT_ID
```

### 3. GKE Cluster Access

Make sure you have access to your GKE cluster:

```bash
# Get cluster credentials
gcloud container clusters get-credentials june-cluster --region us-central1

# Verify cluster access
kubectl cluster-info
kubectl get nodes
```

## Deployment Steps

### Step 1: Configure Terraform Variables

1. Copy the example terraform.tfvars:

```bash
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars
```

2. Edit `terraform.tfvars` with your specific values:

```bash
vim terraform.tfvars
```

Minimal required configuration:

```hcl
# terraform.tfvars
project_id = "main-buffer-469817-v7"  # Your GCP project
region     = "us-central1"
cluster_name = "june-cluster"  # Your existing GKE cluster name

# Harbor configuration
harbor_admin_password = "SecurePassword123!"
domain_name = "june-ai.local"

# Feature toggles
enable_trivy_scanning = true
create_harbor_ingress = false  # Set to true for external access
```

### Step 2: Initialize and Plan

```bash
# Initialize Terraform
terraform init

# Validate configuration
terraform validate

# Review the deployment plan
terraform plan
```

### Step 3: Deploy Harbor

```bash
# Apply the configuration
terraform apply

# Type 'yes' when prompted
```

The deployment will take approximately 5-10 minutes.

### Step 4: Verify Deployment

```bash
# Check Harbor pods
kubectl get pods -n harbor-system

# Check Harbor services
kubectl get svc -n harbor-system

# Check persistent volumes
kubectl get pvc -n harbor-system
```

Expected output:
```
NAME                                    READY   STATUS    RESTARTS   AGE
harbor-core-xxx                         1/1     Running   0          5m
harbor-database-xxx                     1/1     Running   0          5m
harbor-portal-xxx                       1/1     Running   0          5m
harbor-redis-xxx                        1/1     Running   0          5m
harbor-registry-xxx                     1/1     Running   0          5m
harbor-jobservice-xxx                   1/1     Running   0          5m
harbor-trivy-xxx                        1/1     Running   0          5m  # if enabled
```

## Accessing Harbor

### Internal Access (Default)

For internal cluster access:

```bash
# Port forward to access Harbor locally
kubectl port-forward -n harbor-system svc/harbor 8080:80
```

Access Harbor at: http://localhost:8080
- **Username**: `admin`
- **Password**: Your `harbor_admin_password` value

### External Access (Optional)

To enable external access, update your `terraform.tfvars`:

```hcl
create_harbor_ingress = true
enable_harbor_tls     = true  # optional, for HTTPS
harbor_static_ip_name = "harbor-static-ip"  # optional, reserve static IP
```

Then re-apply:

```bash
terraform apply
```

## Using Harbor as Docker Registry

### 1. Login to Harbor

```bash
# For internal access (port-forwarded)
docker login localhost:8080

# For external access
docker login harbor.your-domain.com
```

Use credentials:
- **Username**: `admin`
- **Password**: Your harbor admin password

### 2. Create a Project

Using Harbor web UI:
1. Go to Harbor portal
2. Click "Projects" → "New Project"
3. Create project name (e.g., "june")
4. Set visibility (private/public)

### 3. Push Images

```bash
# Tag your image
docker tag my-app:latest localhost:8080/june/my-app:latest

# Push to Harbor
docker push localhost:8080/june/my-app:latest
```

### 4. Pull Images

```bash
# Pull from Harbor
docker pull localhost:8080/june/my-app:latest
```

## Configuring Kubernetes to Use Harbor

### Create Docker Registry Secret

```bash
# Create secret for Harbor authentication
kubectl create secret docker-registry harbor-regcred \
  --docker-server=localhost:8080 \
  --docker-username=admin \
  --docker-password=YOUR_HARBOR_PASSWORD \
  --docker-email=admin@harbor.local \
  -n your-namespace
```

### Update Deployment to Use Harbor

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      imagePullSecrets:
      - name: harbor-regcred
      containers:
      - name: my-app
        image: localhost:8080/june/my-app:latest
```

## Monitoring and Maintenance

### Useful Commands

```bash
# Check Harbor logs
kubectl logs -n harbor-system -l app=harbor,component=core
kubectl logs -n harbor-system -l app=harbor,component=registry

# Check Harbor status
helm status harbor -n harbor-system

# View Harbor configuration
helm get values harbor -n harbor-system

# Check storage usage
kubectl exec -n harbor-system deploy/harbor-core -- df -h
```

### Backup Considerations

1. **Database Backup**:
   ```bash
   kubectl exec -n harbor-system deploy/harbor-database -- \
     pg_dump -U postgres -d registry > harbor-db-backup.sql
   ```

2. **Registry Data**: Consider using GCS for persistent storage
3. **Configuration**: Keep your terraform.tfvars in version control (without passwords)

## Troubleshooting

### Common Issues

1. **Pods stuck in Pending**:
   ```bash
   kubectl describe pod <pod-name> -n harbor-system
   # Check events for storage or resource issues
   ```

2. **Can't access Harbor UI**:
   - Check port-forward is active: `kubectl get svc -n harbor-system`
   - Verify pods are running: `kubectl get pods -n harbor-system`

3. **Docker login fails**:
   - Verify Harbor is accessible
   - Check username/password
   - For insecure registries, add to Docker daemon config

4. **Storage issues**:
   ```bash
   kubectl get pvc -n harbor-system
   kubectl describe pvc <pvc-name> -n harbor-system
   ```

### Debug Commands

```bash
# Check Terraform outputs
terraform output

# Get deployment events
kubectl get events -n harbor-system --sort-by='.lastTimestamp'

# Check resource usage
kubectl top pods -n harbor-system

# Port forward for debugging
kubectl port-forward -n harbor-system svc/harbor-database 5432:5432
kubectl port-forward -n harbor-system svc/harbor-redis 6379:6379
```

## Configuration Options

### Storage Configuration

```hcl
# Adjust storage sizes based on your needs
harbor_registry_storage_size = "500Gi"  # For large image storage
harbor_database_storage_size = "50Gi"   # For metadata
harbor_redis_storage_size    = "10Gi"   # For cache
```

### Feature Toggles

```hcl
# Enable/disable features
enable_trivy_scanning = true   # Vulnerability scanning
enable_harbor_metrics = true   # Prometheus metrics
create_harbor_ingress = true   # External access
enable_harbor_tls     = true   # HTTPS access
```

### Resource Optimization

For development environments, you can reduce resources by:

1. Disabling Trivy: `enable_trivy_scanning = false`
2. Reducing storage sizes
3. Using smaller node pools

## Security Best Practices

1. **Use strong admin password**: At least 12 characters with mixed case, numbers, symbols
2. **Enable TLS**: Always use HTTPS in production
3. **Network policies**: Restrict network access to Harbor
4. **Image scanning**: Keep Trivy enabled for vulnerability detection
5. **Regular updates**: Keep Harbor chart version updated
6. **Backup**: Implement regular backup procedures

## Upgrading Harbor

To upgrade Harbor to a newer version:

1. Update the chart version in `terraform.tfvars`:
   ```hcl
   harbor_chart_version = "1.16.0"  # New version
   ```

2. Apply the changes:
   ```bash
   terraform plan
   terraform apply
   ```

## Cleanup

To remove Harbor deployment:

```bash
# Destroy Harbor resources
terraform destroy

# Confirm by typing 'yes'
```

**Warning**: This will delete all Harbor data including container images and configuration.

## Additional Resources

- [Harbor Official Documentation](https://goharbor.io/docs/)
- [Harbor Helm Chart](https://github.com/goharbor/harbor-helm)
- [GKE Documentation](https://cloud.google.com/kubernetes-engine/docs)
- [Terraform GCP Provider](https://registry.terraform.io/providers/hashicorp/google/latest/docs)