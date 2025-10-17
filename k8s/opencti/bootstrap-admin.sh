#!/usr/bin/env bash
# OpenCTI Admin Bootstrap Script
# Generates valid admin credentials and patches deployment
set -euo pipefail

NS="${1:-opencti}"
DEP="opencti-server"

ADMIN_EMAIL="${ADMIN_EMAIL:-admin@ozzu.world}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-OpenCTI-$(cat /proc/sys/kernel/random/uuid | cut -d- -f1)!}"
ADMIN_TOKEN="${ADMIN_TOKEN:-$(cat /proc/sys/kernel/random/uuid)}"

echo "Bootstrapping OpenCTI admin in namespace: $NS"
echo "  Email:    $ADMIN_EMAIL"
echo "  Password: $ADMIN_PASSWORD"
echo "  Token:    $ADMIN_TOKEN"
echo

# Check if deployment exists
if ! kubectl get deployment "$DEP" -n "$NS" >/dev/null 2>&1; then
  echo "Error: Deployment $DEP not found in namespace $NS"
  echo "Please deploy OpenCTI first using: helm upgrade --install opencti opencti/opencti -n $NS -f k8s/opencti/values-fixed.yaml"
  exit 1
fi

# Patch deployment with admin credentials
echo "Patching deployment $DEP..."
kubectl patch deployment "$DEP" -n "$NS" --type='json' -p="[
  {\"op\": \"replace\", \"path\": \"/spec/template/spec/containers/0/env\", \"value\": [
    {\"name\": \"APP__ADMIN__EMAIL\", \"value\": \"$ADMIN_EMAIL\"},
    {\"name\": \"APP__ADMIN__PASSWORD\", \"value\": \"$ADMIN_PASSWORD\"},
    {\"name\": \"APP__ADMIN__TOKEN\", \"value\": \"$ADMIN_TOKEN\"},
    {\"name\": \"APP__BASE_PATH\", \"value\": \"/\"},
    {\"name\": \"APP__GRAPHQL__PLAYGROUND__ENABLED\", \"value\": \"false\"},
    {\"name\": \"APP__GRAPHQL__PLAYGROUND__FORCE_DISABLED_INTROSPECTION\", \"value\": \"false\"},
    {\"name\": \"APP__HEALTH_ACCESS_KEY\", \"value\": \"ChangeMe\"},
    {\"name\": \"APP__TELEMETRY__METRICS__ENABLED\", \"value\": \"true\"},
    {\"name\": \"ELASTICSEARCH__URL\", \"value\": \"http://opensearch-cluster-master:9200\"},
    {\"name\": \"MINIO__ACCESS_KEY\", \"value\": \"opencti\"},
    {\"name\": \"MINIO__ENDPOINT\", \"value\": \"opencti-minio\"},
    {\"name\": \"MINIO__PORT\", \"value\": \"9000\"},
    {\"name\": \"MINIO__SECRET_KEY\", \"value\": \"MinIO2024!\"},
    {\"name\": \"MINIO__USE_SSL\", \"value\": \"false\"},
    {\"name\": \"MINIO__BUCKET_NAME\", \"value\": \"opencti-bucket\"},
    {\"name\": \"NODE_OPTIONS\", \"value\": \"--max-old-space-size=8096\"},
    {\"name\": \"PROVIDERS__LOCAL__STRATEGY\", \"value\": \"LocalStrategy\"},
    {\"name\": \"RABBITMQ__HOSTNAME\", \"value\": \"opencti-rabbitmq\"},
    {\"name\": \"RABBITMQ__PASSWORD\", \"value\": \"RabbitMQ2024!\"},
    {\"name\": \"RABBITMQ__PORT\", \"value\": \"5672\"},
    {\"name\": \"RABBITMQ__PORT_MANAGEMENT\", \"value\": \"15672\"},
    {\"name\": \"RABBITMQ__USERNAME\", \"value\": \"opencti\"},
    {\"name\": \"REDIS__HOSTNAME\", \"value\": \"opencti-redis\"},
    {\"name\": \"REDIS__MODE\", \"value\": \"single\"},
    {\"name\": \"REDIS__PORT\", \"value\": \"6379\"}
  ]}
]"

# Delete existing pods to trigger restart with new config
echo "Restarting OpenCTI server pods..."
kubectl delete pods -l opencti.component=server -n "$NS" --ignore-not-found=true

# Wait for rollout to complete
echo "Waiting for deployment rollout..."
kubectl rollout status deployment/"$DEP" -n "$NS" --timeout=10m

echo
echo "✅ Admin bootstrap complete!"
echo "Save these credentials securely:"
echo "APP__ADMIN__EMAIL=$ADMIN_EMAIL"
echo "APP__ADMIN__PASSWORD=$ADMIN_PASSWORD"
echo "APP__ADMIN__TOKEN=$ADMIN_TOKEN"
echo
echo "Monitor logs with: kubectl logs -f deployment/$DEP -n $NS"