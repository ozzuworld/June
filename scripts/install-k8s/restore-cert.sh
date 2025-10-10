#!/bin/bash
# Simple Certificate Restore for June Platform
set -e

BACKUP_FILE="${1:-/root/cert-backups/cert-latest.yaml}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ Backup file not found: $BACKUP_FILE"
    echo "Usage: $0 [backup-file]"
    echo "Available backups:"
    ls -la /root/cert-backups/cert-backup-*.yaml 2>/dev/null || echo "  No backups found"
    exit 1
fi

echo "🔄 Restoring certificate from: $BACKUP_FILE"

# Apply the backup
kubectl apply -f "$BACKUP_FILE"

echo "✅ Certificate restored successfully"
