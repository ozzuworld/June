#!/bin/bash
# June Platform - Phase 4.6: Headscale VPN Server
# Deploy Headscale as a self-hosted Tailscale control server for mesh networking

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

# Source configuration
CONFIG_FILE="${ROOT_DIR}/config.env"
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
fi

# Default values
HEADSCALE_NAMESPACE="${HEADSCALE_NAMESPACE:-headscale}"
HEADSCALE_VERSION="${HEADSCALE_VERSION:-0.23.0}"
HEADSCALE_DATA_SIZE="${HEADSCALE_DATA_SIZE:-1Gi}"
HEADSCALE_IPV4_PREFIX="${HEADSCALE_IPV4_PREFIX:-100.64.0.0/10}"
HEADSCALE_IPV6_PREFIX="${HEADSCALE_IPV6_PREFIX:-fd7a:115c:a1e0::/48}"
HEADSCALE_DERP_ENABLED="${HEADSCALE_DERP_ENABLED:-true}"
WILDCARD_CERT_SECRET="${WILDCARD_CERT_SECRET:-ozzu-world-wildcard-tls}"
WILDCARD_CERT_NAMESPACE="${WILDCARD_CERT_NAMESPACE:-june-services}"

header "Installing Headscale VPN Server"

# Validate required variables
if [ -z "$DOMAIN" ]; then
    error "DOMAIN is not set in config.env"
fi

create_namespace() {
    log "Creating namespace: $HEADSCALE_NAMESPACE"
    kubectl create namespace "$HEADSCALE_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
    success "Namespace created"
}

copy_wildcard_certificate() {
    log "Copying wildcard certificate to Headscale namespace..."
    
    # Check if wildcard cert exists in source namespace
    if kubectl get secret "$WILDCARD_CERT_SECRET" -n "$WILDCARD_CERT_NAMESPACE" &>/dev/null; then
        # Copy the certificate to headscale namespace
        kubectl get secret "$WILDCARD_CERT_SECRET" -n "$WILDCARD_CERT_NAMESPACE" -o yaml | \
            sed "s/namespace: $WILDCARD_CERT_NAMESPACE/namespace: $HEADSCALE_NAMESPACE/" | \
            kubectl apply -f -
        success "Wildcard certificate copied to $HEADSCALE_NAMESPACE namespace"
    else
        warn "Wildcard certificate not found in $WILDCARD_CERT_NAMESPACE namespace"
        warn "Will use cert-manager to create a new certificate"
    fi
}

create_persistent_volume() {
    log "Creating persistent volume for Headscale data..."
    
    # Create directory on host
    mkdir -p /mnt/data/headscale
    chmod 755 /mnt/data/headscale
    
    # Create PV
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: headscale-pv
  labels:
    app: headscale
spec:
  capacity:
    storage: ${HEADSCALE_DATA_SIZE}
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /mnt/data/headscale
    type: DirectoryOrCreate
EOF

    # Create PVC
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: headscale-data
  namespace: ${HEADSCALE_NAMESPACE}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: ${HEADSCALE_DATA_SIZE}
  storageClassName: ""
  selector:
    matchLabels:
      app: headscale
EOF

    success "Persistent volume created"
}

create_config() {
    log "Creating Headscale configuration..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: headscale-config
  namespace: ${HEADSCALE_NAMESPACE}
data:
  config.yaml: |
    server_url: https://headscale.${DOMAIN}
    listen_addr: 0.0.0.0:8080
    metrics_listen_addr: 127.0.0.1:9090
    
    grpc_listen_addr: 0.0.0.0:50443
    grpc_allow_insecure: false
    
    private_key_path: /var/lib/headscale/private.key
    noise:
      private_key_path: /var/lib/headscale/noise_private.key
    
    prefixes:
      v4: ${HEADSCALE_IPV4_PREFIX}
      v6: ${HEADSCALE_IPV6_PREFIX}
    
    derp:
      server:
        enabled: ${HEADSCALE_DERP_ENABLED}
        region_id: 999
        region_code: "june"
        region_name: "June Headscale DERP"
        stun_listen_addr: "0.0.0.0:3478"
        private_key_path: /var/lib/headscale/derp_server_private.key
      urls:
        - https://controlplane.tailscale.com/derpmap/default
      paths: []
      auto_update_enabled: true
      update_frequency: 24h
    
    database:
      type: sqlite3
      sqlite:
        path: /var/lib/headscale/db.sqlite
        write_ahead_log: true
    
    dns:
      nameservers:
        global:
          - 1.1.1.1
          - 1.0.0.1
        split:
          svc.cluster.local:
            - 10.96.0.10
      magic_dns: false
    
    log:
      format: text
      level: info
    
    policy:
      mode: database
    
    disable_check_updates: true
    
    ephemeral_node_inactivity_timeout: 30m
    node_update_check_interval: 10s
EOF

    success "Configuration created"
}

deploy_headscale() {
    log "Deploying Headscale..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: headscale
  namespace: ${HEADSCALE_NAMESPACE}
  labels:
    app: headscale
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: headscale
  template:
    metadata:
      labels:
        app: headscale
    spec:
      containers:
      - name: headscale
        image: headscale/headscale:${HEADSCALE_VERSION}
        imagePullPolicy: IfNotPresent
        command: ["headscale", "serve"]
        ports:
        - name: http
          containerPort: 8080
          protocol: TCP
        - name: grpc
          containerPort: 50443
          protocol: TCP
        - name: metrics
          containerPort: 9090
          protocol: TCP
        - name: stun
          containerPort: 3478
          protocol: UDP
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        volumeMounts:
        - name: config
          mountPath: /etc/headscale
          readOnly: true
        - name: data
          mountPath: /var/lib/headscale
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
      volumes:
      - name: config
        configMap:
          name: headscale-config
      - name: data
        persistentVolumeClaim:
          claimName: headscale-data
---
apiVersion: v1
kind: Service
metadata:
  name: headscale
  namespace: ${HEADSCALE_NAMESPACE}
  labels:
    app: headscale
spec:
  type: ClusterIP
  ports:
  - name: http
    port: 8080
    targetPort: 8080
    protocol: TCP
  - name: grpc
    port: 50443
    targetPort: 50443
    protocol: TCP
  - name: metrics
    port: 9090
    targetPort: 9090
    protocol: TCP
  selector:
    app: headscale
---
apiVersion: v1
kind: Service
metadata:
  name: headscale-stun
  namespace: ${HEADSCALE_NAMESPACE}
  labels:
    app: headscale
spec:
  type: NodePort
  ports:
  - name: stun
    port: 3478
    targetPort: 3478
    protocol: UDP
    nodePort: 30478
  selector:
    app: headscale
EOF

    success "Headscale deployment created"
}

create_derp_service() {
    log "Creating DERP relay service..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: headscale-derp
  namespace: ${HEADSCALE_NAMESPACE}
  labels:
    app: headscale
spec:
  type: ClusterIP
  ports:
  - name: derp-https
    port: 443
    targetPort: 8080
    protocol: TCP
  selector:
    app: headscale
EOF

    success "DERP service created"
}

create_ingress() {
    log "Creating Ingress for Headscale control server..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: headscale
  namespace: ${HEADSCALE_NAMESPACE}
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - headscale.${DOMAIN}
    secretName: ${WILDCARD_CERT_SECRET}
  rules:
  - host: headscale.${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: headscale
            port:
              number: 8080
EOF

    success "Control server ingress created"
}

create_derp_ingress() {
    log "Creating Ingress for DERP relay server..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: headscale-derp
  namespace: ${HEADSCALE_NAMESPACE}
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    nginx.ingress.kubernetes.io/ssl-passthrough: "false"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - tail.${DOMAIN}
    secretName: ${WILDCARD_CERT_SECRET}
  rules:
  - host: tail.${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: headscale-derp
            port:
              number: 443
EOF

    success "DERP relay ingress created"
}

configure_firewall() {
    log "Configuring firewall for STUN port..."
    
    # Check if UFW is active
    if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
        log "Allowing STUN port 30478/UDP through UFW..."
        ufw allow 30478/udp >/dev/null 2>&1 || true
        success "UFW rule added"
    elif command -v firewall-cmd &>/dev/null; then
        log "Allowing STUN port 30478/UDP through firewalld..."
        firewall-cmd --add-port=30478/udp --permanent >/dev/null 2>&1 || true
        firewall-cmd --reload >/dev/null 2>&1 || true
        success "Firewalld rule added"
    else
        warn "No firewall detected, skipping firewall configuration"
    fi
}

wait_for_deployment() {
    log "Waiting for Headscale to be ready..."
    
    kubectl wait --for=condition=available deployment/headscale \
        -n "$HEADSCALE_NAMESPACE" \
        --timeout=300s
    
    sleep 5
    success "Headscale is ready"
}

create_default_user() {
    log "Creating default Headscale user..."
    
    # Try to create default user (ignore if already exists)
    kubectl exec -n "$HEADSCALE_NAMESPACE" deployment/headscale -- \
        headscale users create default 2>/dev/null || true
    
    success "Default user ready"
}

generate_preauth_key() {
    log "Generating pre-authentication key..."
    
    # Generate a reusable preauth key valid for 24 hours
    PREAUTH_KEY=$(kubectl exec -n "$HEADSCALE_NAMESPACE" deployment/headscale -- \
        headscale --user default preauthkeys create --reusable --expiration 24h 2>/dev/null | tail -1)
    
    if [ -n "$PREAUTH_KEY" ]; then
        info "Pre-authentication key generated (valid for 24h)"
        echo ""
        echo "================================================================"
        echo "🔑 Headscale Pre-Auth Key (save this!)"
        echo "================================================================"
        echo "$PREAUTH_KEY"
        echo "================================================================"
        echo ""
    fi
}

show_summary() {
    header "Headscale Installation Complete"
    
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    
    echo "📡 Headscale VPN Server"
    echo "  Control Server:  https://headscale.${DOMAIN}"
    echo "  DERP Relay:      https://tail.${DOMAIN}"
    echo "  STUN Server:     ${EXTERNAL_IP}:30478 (UDP)"
    echo ""
    echo "👥 User Management"
    echo "  Create user:     kubectl exec -n ${HEADSCALE_NAMESPACE} deployment/headscale -- headscale users create <username>"
    echo "  List users:      kubectl exec -n ${HEADSCALE_NAMESPACE} deployment/headscale -- headscale users list"
    echo ""
    echo "🔑 Pre-Auth Keys"
    echo "  Generate key:    kubectl exec -n ${HEADSCALE_NAMESPACE} deployment/headscale -- headscale --user default preauthkeys create --reusable --expiration 24h"
    echo "  List keys:       kubectl exec -n ${HEADSCALE_NAMESPACE} deployment/headscale -- headscale --user default preauthkeys list"
    echo ""
    echo "💻 Connect Clients"
    echo "  Linux/macOS:     tailscale up --login-server=https://headscale.${DOMAIN} --authkey=<key>"
    echo "  Interactive:     tailscale up --login-server=https://headscale.${DOMAIN}"
    echo ""
    echo "🌐 Manage Nodes"
    echo "  List nodes:      kubectl exec -n ${HEADSCALE_NAMESPACE} deployment/headscale -- headscale nodes list"
    echo "  Expire node:     kubectl exec -n ${HEADSCALE_NAMESPACE} deployment/headscale -- headscale nodes expire <node-id>"
    echo "  Delete node:     kubectl exec -n ${HEADSCALE_NAMESPACE} deployment/headscale -- headscale nodes delete <node-id>"
    echo ""
    echo "📊 Status & Logs"
    echo "  Check pods:      kubectl get pods -n ${HEADSCALE_NAMESPACE}"
    echo "  View logs:       kubectl logs -n ${HEADSCALE_NAMESPACE} deployment/headscale -f"
    echo "  Test health:     curl https://headscale.${DOMAIN}/health"
    echo ""
}

# Main installation flow
main() {
    create_namespace
    copy_wildcard_certificate
    create_persistent_volume
    create_config
    deploy_headscale
    create_derp_service
    create_ingress
    create_derp_ingress
    configure_firewall
    wait_for_deployment
    create_default_user
    generate_preauth_key
    show_summary
}

main
