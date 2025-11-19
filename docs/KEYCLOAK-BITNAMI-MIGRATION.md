# Keycloak Migration Guide: Custom Image → Bitnami Helm Chart

## Overview

This guide covers migrating from the custom `ozzuworld/june-idp` Docker image to the official **Bitnami Keycloak Helm chart** - the industry-standard solution for deploying Keycloak in Kubernetes.

## Why Migrate?

### Problems with Custom Image
- ❌ Docker Hub rate limiting (429 Too Many Requests)
- ❌ Manual image maintenance and rebuilds
- ❌ No automatic updates or security patches
- ❌ Custom deployment manifests to maintain

### Benefits of Bitnami Chart
- ✅ **No rate limiting**: Uses Quay.io instead of Docker Hub
- ✅ **Industry standard**: Battle-tested by thousands of companies
- ✅ **Automatic updates**: Easy upgrades via Helm
- ✅ **Built-in features**: Metrics, monitoring, auto-scaling
- ✅ **Better maintained**: Regular security patches
- ✅ **Simpler operations**: Single `helm upgrade` command

## Migration Options

### Option 1: Automated Migration (Recommended)

Use our automated migration script that handles everything:

```bash
cd /home/user/June
./scripts/install/migrate-to-bitnami-keycloak.sh
```

**Features:**
- ✅ Prerequisite checks (helm, kubectl, namespace)
- ✅ Automatic PostgreSQL backup
- ✅ Data migration support
- ✅ Rollback capability
- ✅ Verification steps
- ✅ Clear error messages

**Migration modes:**
1. **Fresh install**: Deletes all Keycloak data (clean start)
2. **Data migration**: Preserves all realms, users, and settings (recommended for production)

### Option 2: Manual Migration

If you prefer manual control, follow the step-by-step guide below.

---

## Automated Migration Guide

### Prerequisites

1. **Helm 3.x installed**
   ```bash
   helm version
   ```

2. **kubectl configured** for your cluster
   ```bash
   kubectl cluster-info
   ```

3. **june-services namespace** exists
   ```bash
   kubectl get namespace june-services
   ```

### Step-by-Step Process

#### Step 1: Review Configuration

Edit the Keycloak values if needed:

```bash
vim /home/user/June/helm/keycloak-values.yaml
```

**Key settings to review:**
- `auth.adminUser` and `auth.adminPassword`
- `ingress.hostname` (should be `idp.ozzu.world`)
- `postgresql.auth.password`
- `resources.limits` and `resources.requests`

#### Step 2: Run Migration Script

```bash
cd /home/user/June
./scripts/install/migrate-to-bitnami-keycloak.sh
```

The script will:
1. ✅ Check prerequisites (helm, kubectl)
2. ✅ Add Bitnami Helm repository
3. ✅ Detect existing Keycloak deployment
4. ✅ Prompt for migration type (fresh vs data migration)
5. ✅ Backup PostgreSQL data (if data migration selected)
6. ✅ Remove old deployment
7. ✅ Install Bitnami Keycloak chart
8. ✅ Restore data (if data migration selected)
9. ✅ Verify installation

#### Step 3: Verify Migration

1. **Check pod status:**
   ```bash
   kubectl get pods -n june-services -l app.kubernetes.io/name=keycloak
   ```

   Expected output:
   ```
   NAME                        READY   STATUS    RESTARTS   AGE
   keycloak-xxxxxxxxx-xxxxx    1/1     Running   0          2m
   ```

2. **Check logs:**
   ```bash
   kubectl logs -n june-services -l app.kubernetes.io/name=keycloak
   ```

3. **Access Keycloak UI:**
   ```
   https://idp.ozzu.world
   ```

   Login with:
   - Username: `admin`
   - Password: `Pokemon123!` (CHANGE THIS!)

4. **Verify data** (if migrated):
   - Check that your realms are present
   - Verify users exist
   - Test authentication

#### Step 4: Update Application References

The service name has changed. Update any references in your applications:

**Old:**
```yaml
KEYCLOAK_URL: http://june-idp.june-services.svc.cluster.local:8080
```

**New:**
```yaml
KEYCLOAK_URL: http://keycloak.june-services.svc.cluster.local:8080
```

**Files to update:**
- `helm/june-platform/templates/june-orchestrator.yaml:106`
- Any other services that connect to Keycloak

---

## Manual Migration Guide

### Option A: Fresh Install (No Data Migration)

```bash
# 1. Add Bitnami repository
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# 2. Remove old deployment
kubectl delete deployment june-idp -n june-services
kubectl delete statefulset postgresql -n june-services
kubectl delete pvc postgresql-pvc -n june-services
kubectl delete pv postgresql-pv
kubectl delete service postgresql -n june-services
kubectl delete service june-idp -n june-services

# 3. Install Bitnami Keycloak
helm install keycloak bitnami/keycloak \
  --namespace june-services \
  --values /home/user/June/helm/keycloak-values.yaml \
  --wait \
  --timeout 10m

# 4. Verify
kubectl get pods -n june-services -l app.kubernetes.io/name=keycloak
```

### Option B: Data Migration (Preserves Users/Realms)

```bash
# 1. Backup PostgreSQL
kubectl exec -n june-services postgresql-0 -- bash -c \
  "PGPASSWORD=Pokemon123! pg_dump -U keycloak -d keycloak" > /tmp/keycloak-backup.sql

# 2. Add Bitnami repository
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# 3. Remove old deployment (keep data temporarily)
kubectl delete deployment june-idp -n june-services

# 4. Install Bitnami Keycloak
helm install keycloak bitnami/keycloak \
  --namespace june-services \
  --values /home/user/June/helm/keycloak-values.yaml \
  --wait \
  --timeout 10m

# 5. Wait for PostgreSQL to be ready
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=postgresql \
  -n june-services \
  --timeout=300s

# 6. Restore data
POSTGRES_POD=$(kubectl get pods -n june-services \
  -l app.kubernetes.io/name=postgresql \
  -o jsonpath='{.items[0].metadata.name}')

cat /tmp/keycloak-backup.sql | kubectl exec -i -n june-services $POSTGRES_POD -- \
  bash -c "PGPASSWORD=Pokemon123! psql -U keycloak -d keycloak"

# 7. Restart Keycloak to pick up data
kubectl rollout restart deployment -l app.kubernetes.io/name=keycloak -n june-services
kubectl rollout status deployment -l app.kubernetes.io/name=keycloak -n june-services

# 8. Verify
kubectl get pods -n june-services -l app.kubernetes.io/name=keycloak
```

---

## Configuration Reference

### Helm Values File

Location: `/home/user/June/helm/keycloak-values.yaml`

**Key configurations:**

```yaml
# Admin credentials
auth:
  adminUser: admin
  adminPassword: Pokemon123!  # CHANGE IN PRODUCTION

# Image (Bitnami - required for Bitnami chart)
image:
  registry: docker.io
  repository: bitnami/keycloak
  tag: "26.0.4"
  pullPolicy: IfNotPresent

# Resources
resources:
  requests:
    memory: "1Gi"
    cpu: "500m"
  limits:
    memory: "2Gi"
    cpu: "1000m"

# PostgreSQL (bundled)
postgresql:
  enabled: true
  auth:
    username: keycloak
    password: Pokemon123!
    database: keycloak
  primary:
    persistence:
      storageClass: fast-ssd
      size: 10Gi

# Ingress
ingress:
  enabled: true
  hostname: idp.ozzu.world
  tls: true
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
```

### Updating Configuration

To update Keycloak configuration:

```bash
# 1. Edit values file
vim /home/user/June/helm/keycloak-values.yaml

# 2. Apply changes
helm upgrade keycloak bitnami/keycloak \
  --namespace june-services \
  --values /home/user/June/helm/keycloak-values.yaml

# 3. Verify
kubectl rollout status deployment -l app.kubernetes.io/name=keycloak -n june-services
```

---

## Post-Migration Tasks

### 1. Update Service References

Update all applications that connect to Keycloak:

**Old service name:**
```
june-idp.june-services.svc.cluster.local:8080
```

**New service name:**
```
keycloak.june-services.svc.cluster.local:8080
```

**Files to check:**
- `helm/june-platform/templates/june-orchestrator.yaml`
- Any custom application configurations

### 2. Verify Monitoring Integration

Keycloak now exposes Prometheus metrics:

```bash
# Check ServiceMonitor
kubectl get servicemonitor -n monitoring keycloak

# View metrics endpoint
kubectl port-forward -n june-services svc/keycloak 8080:8080
curl http://localhost:8080/metrics
```

### 3. Security Hardening

**Change default passwords:**
```bash
# Update admin password via Keycloak UI
# Or update Helm values and upgrade
```

**Enable additional security features** in `helm/keycloak-values.yaml`:
```yaml
extraEnvVars:
  - name: KC_HOSTNAME_STRICT
    value: "true"  # Enable strict hostname checking (production)
```

### 4. Backup Strategy

**Regular backups:**
```bash
# Automated backup script
cat > /usr/local/bin/backup-keycloak.sh <<'EOF'
#!/bin/bash
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
POSTGRES_POD=$(kubectl get pods -n june-services \
  -l app.kubernetes.io/name=postgresql \
  -o jsonpath='{.items[0].metadata.name}')

kubectl exec -n june-services $POSTGRES_POD -- bash -c \
  "PGPASSWORD=Pokemon123! pg_dump -U keycloak -d keycloak" \
  > /backup/keycloak-${BACKUP_DATE}.sql

# Keep last 7 days
find /backup -name "keycloak-*.sql" -mtime +7 -delete
EOF

chmod +x /usr/local/bin/backup-keycloak.sh

# Add to cron
crontab -e
# Add: 0 2 * * * /usr/local/bin/backup-keycloak.sh
```

---

## Troubleshooting

### ImagePullBackOff Errors

If you still see ImagePullBackOff after migration:

```bash
# Check events
kubectl describe pod -n june-services -l app.kubernetes.io/name=keycloak

# Verify image is Bitnami (required for Bitnami chart)
kubectl get deployment -n june-services -l app.kubernetes.io/name=keycloak \
  -o jsonpath='{.items[0].spec.template.spec.containers[0].image}'

# Should output: docker.io/bitnami/keycloak:26.0.4
```

### Pod Not Ready

```bash
# Check pod status
kubectl get pods -n june-services -l app.kubernetes.io/name=keycloak

# View logs
kubectl logs -n june-services -l app.kubernetes.io/name=keycloak

# Check events
kubectl get events -n june-services --sort-by='.lastTimestamp'
```

### Database Connection Issues

```bash
# Check PostgreSQL pod
kubectl get pods -n june-services -l app.kubernetes.io/name=postgresql

# Test database connection
POSTGRES_POD=$(kubectl get pods -n june-services \
  -l app.kubernetes.io/name=postgresql \
  -o jsonpath='{.items[0].metadata.name}')

kubectl exec -it -n june-services $POSTGRES_POD -- \
  psql -U keycloak -d keycloak -c "SELECT version();"
```

### Ingress/TLS Issues

```bash
# Check ingress
kubectl get ingress -n june-services

# Check certificate
kubectl get certificate -n june-services

# Test TLS
curl -vI https://idp.ozzu.world
```

### Rollback to Previous Version

If migration fails and you need to rollback:

```bash
# 1. Remove Bitnami Keycloak
helm uninstall keycloak -n june-services

# 2. Restore old deployment (if you kept the manifests)
kubectl apply -f helm/june-platform/templates/june-idp.yaml
kubectl apply -f helm/june-platform/templates/postgresql.yaml

# 3. Restore database backup (if needed)
kubectl exec -i -n june-services postgresql-0 -- \
  bash -c "PGPASSWORD=Pokemon123! psql -U keycloak -d keycloak" \
  < /tmp/keycloak-backup.sql
```

---

## Useful Commands

### Check Helm Release

```bash
# List releases
helm list -n june-services

# Get release values
helm get values keycloak -n june-services

# Get release status
helm status keycloak -n june-services
```

### Update Keycloak

```bash
# Check for chart updates
helm repo update
helm search repo bitnami/keycloak

# Upgrade to new version
helm upgrade keycloak bitnami/keycloak \
  --namespace june-services \
  --values /home/user/June/helm/keycloak-values.yaml
```

### Uninstall Keycloak

```bash
# Remove Helm release
helm uninstall keycloak -n june-services

# Remove PVCs (optional - destroys data!)
kubectl delete pvc -n june-services -l app.kubernetes.io/name=postgresql
kubectl delete pvc -n june-services -l app.kubernetes.io/name=keycloak
```

---

## References

- [Bitnami Keycloak Chart Documentation](https://github.com/bitnami/charts/tree/main/bitnami/keycloak)
- [Keycloak Official Documentation](https://www.keycloak.org/documentation)
- [Helm Documentation](https://helm.sh/docs/)
- Migration Script: `/home/user/June/scripts/install/migrate-to-bitnami-keycloak.sh`
- Values File: `/home/user/June/helm/keycloak-values.yaml`

---

## Support

If you encounter issues during migration:

1. Check the troubleshooting section above
2. Review pod logs: `kubectl logs -n june-services -l app.kubernetes.io/name=keycloak`
3. Check Helm status: `helm status keycloak -n june-services`
4. Verify values file: `helm get values keycloak -n june-services`
5. Contact the development team with error details
