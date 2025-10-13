#!/usr/bin/env bash
set -euo pipefail

: "${PUBIP:?Set PUBIP to your node's public IP, e.g. PUBIP=35.222.99.133}"
: "${STUNNER_NS:=stunner}"

echo "==> Creating namespaces"
kubectl apply -f k8s/stunner/00-namespaces.yaml

echo "==> Installing/Upgrading STUNner operator (namespace: stunner-system)"
helm repo add stunner https://l7mp.io/stunner >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install stunner stunner/stunner-gateway-operator -n stunner-system --create-namespace
kubectl -n stunner-system rollout status deploy/stunner-gateway-operator

echo "==> Creating TURN Secret (from env TURN_USERNAME / TURN_PASSWORD)"
: "${TURN_USERNAME:=demo}"
: "${TURN_PASSWORD:=supersecret}"
kubectl -n "$STUNNER_NS" create secret generic stunner-auth-secret \
  --from-literal=type=static \
  --from-literal=username="$TURN_USERNAME" \
  --from-literal=password="$TURN_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Applying hostNetwork dataplane + config + class"
kubectl apply -f k8s/stunner/20-dataplane-hostnet.yaml
kubectl apply -f k8s/stunner/30-gatewayconfig.yaml
kubectl apply -f k8s/stunner/40-gatewayclass.yaml

echo "==> Rendering and applying Gateway with PUBIP=${PUBIP}"
envsubst < k8s/stunner/50-gateway.yaml | kubectl apply -f -

echo "==> Applying UDPRoute to LiveKit"
kubectl apply -f k8s/stunner/60-udproute-livekit.yaml

echo "==> Waiting for gateway to be Programmed=True"
for i in {1..30}; do
  READY=$(kubectl -n "$STUNNER_NS" get gateway stunner-gateway -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}' || true)
  [[ "$READY" == "True" ]] && break
  sleep 2
done
kubectl -n "$STUNNER_NS" get gateway stunner-gateway -o wide
