#!/bin/bash
# Simple Certificate Backup for June Platform
set -e

# Load configuration
if [ -f ".env" ]; then
    source .env
else
    echo "❌ .env file not found"
    exit 1
fi

NAMESPACE="june-services"
CERT_SECRET="${PRIMARY_DOMAIN//./-}-wildcard-tls"
BACKUP_DIR="/root/cert-backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$BACKUP_DIR"

echo "🔐 Backing up certificate: $CERT_SECRET for domain: $PRIMARY_DOMAIN"

# Backup certificate secret
kubectl get secret "$CERT_SECRET" -n "$NAMESPACE" -o yaml > "$BACKUP_DIR/cert-backup-$TIMESTAMP.yaml"

# Create latest symlink
ln -sf "cert-backup-$TIMESTAMP.yaml" "$BACKUP_DIR/cert-latest.yaml"

# Cleanup old backups (keep last 5)
cd "$BACKUP_DIR" && ls -t cert-backup-*.yaml 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true

echo "✅ Certificate backed up to: $BACKUP_DIR/cert-backup-$TIMESTAMP.yaml"

# Show certificate info
CERT_DATA=$(kubectl get secret "$CERT_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.tls\.crt}' 2>/dev/null || echo "")
if [ -n "$CERT_DATA" ]; then
    echo "$CERT_DATA" | base64 -d > /tmp/cert.crt
    EXPIRY=$(openssl x509 -in /tmp/cert.crt -noout -enddate 2>/dev/null | cut -d= -f2 || echo "unknown")
    echo "📋 Certificate expires: $EXPIRY"
    rm /tmp/cert.crt
fi
