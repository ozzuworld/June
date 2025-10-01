#!/usr/bin/env bash
set -euo pipefail

NS="ingress-nginx"
RELEASE="ingress-nginx"
CHART="ingress-nginx/ingress-nginx"
VALUES_FILE="${1:-ops/ingress-nginx-values.yaml}"

echo "🔎 Ensuring namespace ${NS} exists..."
kubectl get ns "${NS}" >/dev/null 2>&1 || kubectl create ns "${NS}"

# Ensure Helm repo exists
if ! helm repo list 2>/dev/null | grep -q 'ingress-nginx'; then
  echo "➕ Adding Helm repo ingress-nginx..."
  helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
fi
echo "🔄 Updating helm repos..."
helm repo update

# Some clusters may have leftover cluster-scoped objects that block install
echo "🧹 Optional cleanup of stale cluster-scoped objects (safe if absent)..."
kubectl get validatingwebhookconfigurations.admissionregistration.k8s.io ingress-nginx-admission >/dev/null 2>&1 \
  && kubectl delete validatingwebhookconfiguration ingress-nginx-admission || true
kubectl get ingressclass.networking.k8s.io nginx >/dev/null 2>&1 \
  && kubectl delete ingressclass nginx || true

echo "🚀 Installing/Upgrading ${RELEASE} with ${VALUES_FILE}..."
helm upgrade --install "${RELEASE}" "${CHART}" \
  -n "${NS}" \
  -f "${VALUES_FILE}" \
  --wait --timeout 5m

echo "✅ ingress-nginx is installed."
kubectl -n "${NS}" get pods -o wide
echo "🔊 Host ports open:"
ss -lntp | egrep ':(80|443)\b' || true
