
# STUNner clean setup (GKE)

## What these files do
- `00-namespace.yaml` — creates `stunner` (gateway) and `media` (your media apps).
- `10-turn-rest-secret.yaml` — holds the HMAC secret for **REST TURN credentials**. Change the value.
- `20-gatewayconfig.yaml` — global STUNner settings: realm, auth type, **relay port range** (49160–49200), and listeners (3478/5349).
- `30-gateway.yaml` — exposes STUN/TURN via a **LoadBalancer** (you’ll get a public IP).
- `40-udproute-media.yaml` — routes TURN-relayed UDP to your backend `Service` (example name `livekit-udp` on port 7882).
- `50-livekit-service.yaml` — example ClusterIP `Service` with a **single UDP port** (works for LiveKit/mediasoup). Replace with your real Service if different.

## Apply (after you install the STUNner operator via Helm)
```bash
kubectl apply -f 00-namespace.yaml
kubectl apply -f 10-turn-rest-secret.yaml
kubectl apply -f 20-gatewayconfig.yaml
kubectl apply -f 30-gateway.yaml
kubectl apply -f 40-udproute-media.yaml
kubectl apply -f 50-livekit-service.yaml   # or your own Service
```

Then get the external IP:
```bash
kubectl -n stunner get gateway stunner-gateway -o wide
```

Point clients at:
- `stun:turn.ozzu.world:3478`
- `turn:turn.ozzu.world:3478?transport=udp`
- `turns:turn.ozzu.world:5349?transport=tcp`

Use **REST TURN creds**: username like `<expiry-epoch>:<user>`, password = HMAC(secret, username).

## Janus note
If you use **Janus**, configure a **narrow RTP port range** in Janus (e.g., `49160-49200`) and create a backend `Service` exposing the single UDP port your Janus gateway is configured to use for ICE/DTLS (or use STUNner's StaticService to point directly to pod IPs). Many teams find LiveKit/mediasoup simpler with STUNner because they use a single fixed UDP port for the worker.
