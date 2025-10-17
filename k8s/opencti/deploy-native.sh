#!/bin/bash
# File: k8s/opencti/deploy-native.sh
# Native Kubernetes deployment for OpenCTI (no Helm bullshit)

set -e

echo "🚀 Deploying OpenCTI with native Kubernetes manifests..."

# Remove the broken Helm deployment first
echo "🗑️ Cleaning up broken Helm deployment..."
helm uninstall opencti -n opencti 2>/dev/null || echo "No Helm release to remove"

# Deploy MinIO, RabbitMQ, Redis using Helm (these work)
echo "📦 Deploying dependencies..."
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Deploy MinIO
helm upgrade --install opencti-minio bitnami/minio \
  --namespace opencti \
  --create-namespace \
  --set auth.rootUser=opencti \
  --set auth.rootPassword=MinIO2024! \
  --set mode=standalone \
  --set persistence.enabled=false \
  --wait

# Deploy RabbitMQ
helm upgrade --install opencti-rabbitmq bitnami/rabbitmq \
  --namespace opencti \
  --set auth.username=opencti \
  --set auth.password=RabbitMQ2024! \
  --set persistence.enabled=false \
  --set clustering.enabled=false \
  --wait

# Deploy Redis
helm upgrade --install opencti-redis bitnami/redis \
  --namespace opencti \
  --set architecture=standalone \
  --set auth.enabled=false \
  --set master.persistence.enabled=false \
  --wait

echo "🔧 Deploying OpenCTI server and worker..."
# Deploy OpenCTI server and worker with native manifests
kubectl apply -f opencti-server-deployment.yaml
kubectl apply -f opencti-worker-deployment.yaml
kubectl apply -f opencti-service.yaml

# Deploy ingress
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: opencti-ingress
  namespace: opencti
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    kubernetes.io/ingress.class: nginx
spec:
  tls:
  - hosts:
    - opencti.ozzu.world
    secretName: ozzu-world-wildcard-tls
  rules:
  - host: opencti.ozzu.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: opencti-server
            port:
              number: 4000
EOF

echo "✅ OpenCTI deployed with native Kubernetes manifests"
echo "🔍 Check status: kubectl get pods -n opencti"
echo "📋 Check logs: kubectl logs -n opencti deployment/opencti-server -f"
echo "🌐 Access URL: https://opencti.ozzu.world"