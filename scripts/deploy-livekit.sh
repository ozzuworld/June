#!/usr/bin/env bash
set -euo pipefail
helm repo add livekit https://helm.livekit.io >/dev/null 2>&1 || true
helm repo update >/dev/null
kubectl create ns media >/dev/null 2>&1 || true
helm upgrade --install livekit livekit/livekit-server -n media -f k8s/livekit/livekit-values.yaml
# Ensure UDP Service exists (idempotent)
kubectl -n media get svc livekit-udp >/dev/null 2>&1 || {
cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: livekit-udp
  namespace: media
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/instance: livekit
    app.kubernetes.io/name: livekit-server
  ports:
    - name: rtp-udp
      protocol: UDP
      port: 7882
      targetPort: 7882
YAML
}
kubectl -n media get svc livekit-udp -o wide
