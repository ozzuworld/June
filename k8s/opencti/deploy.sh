#!/bin/bash
# File: k8s/opencti/deploy.sh
# OpenCTI deployment script

set -e

helm repo add opencti https://devops-ia.github.io/helm-opencti
helm repo update

helm upgrade --install opencti opencti/opencti \
  --namespace opencti \
  --create-namespace \
  -f values.yaml \
  --timeout 15m \
  --wait

echo "✅ OpenCTI deployed"
echo "Monitor: kubectl get pods -n opencti -w"