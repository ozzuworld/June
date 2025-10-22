#!/bin/bash
# Patch headscale config and restart ephemeral deployment
set -euo pipefail

kubectl apply -f k8s/headscale/headscale-configmap.yaml
kubectl -n headscale rollout restart deploy/headscale-ephemeral
kubectl -n headscale rollout status deploy/headscale-ephemeral
kubectl -n headscale logs deploy/headscale-ephemeral --tail=200
