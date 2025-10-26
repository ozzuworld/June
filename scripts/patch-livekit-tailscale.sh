#!/bin/bash

# LiveKit Tailscale Sidecar Patch Script
# This script patches an existing LiveKit deployment to add Tailscale sidecar
# for Headscale connectivity

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
LIVEKIT_NAMESPACE="media"
JUNE_NAMESPACE="june-services"
HEADSCALE_NAMESPACE="headscale"
HEADSCALE_SERVER="https://headscale.ozzu.world"

# Get script directory for relative path resolution
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}🎵 Adding Tailscale Sidecar to LiveKit${NC}"
echo "=========================================="
echo "Root directory: $ROOT_DIR"
echo "LiveKit namespace: $LIVEKIT_NAMESPACE"
echo "Headscale server: $HEADSCALE_SERVER"

# Function to print status messages
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check prerequisites
echo -e "${BLUE}📋 Checking prerequisites...${NC}"

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    print_error "kubectl is not installed or not in PATH"
    exit 1
fi

# Check if jq is available
if ! command -v jq &> /dev/null; then
    print_error "jq is required but not installed. Please install jq and rerun."
    exit 1
fi

# Check if headscale namespace exists
if ! kubectl get namespace "$HEADSCALE_NAMESPACE" &> /dev/null; then
    print_error "Headscale namespace '$HEADSCALE_NAMESPACE' not found"
    exit 1
fi

# Check if LiveKit deployment exists
if ! kubectl get deployment -n "$LIVEKIT_NAMESPACE" -l "app.kubernetes.io/name=livekit" &> /dev/null; then
    print_error "LiveKit deployment not found in namespace '$LIVEKIT_NAMESPACE'"
    print_warning "Please ensure LiveKit is deployed first"
    exit 1
fi

print_status "Prerequisites check completed"

# Create headscale alias function (non-TTY to avoid control sequences)
headscale_cmd() {
    kubectl -n "$HEADSCALE_NAMESPACE" exec -i deployment/headscale -c headscale -- headscale "$@"
}

# Step 1: Create Headscale user for LiveKit
echo -e "\n${BLUE}👥 Creating Headscale user for LiveKit...${NC}"

if headscale_cmd users create livekit 2>/dev/null; then
    print_status "Created user: livekit"
else
    print_warning "User livekit may already exist"
fi

# Step 2: Generate auth key for LiveKit
echo -e "\n${BLUE}🔑 Generating authentication key for LiveKit...${NC}"

OUTPUT_JSON="$(headscale_cmd --output json --user livekit preauthkeys create --reusable --expiration 180d 2>/dev/null || true)"
LIVEKIT_KEY="$(printf "%s" "$OUTPUT_JSON" | jq -r '.key // .authKey // .auth_key // empty' 2>/dev/null | head -n1)"

if [ -n "$LIVEKIT_KEY" ] && [ ${#LIVEKIT_KEY} -ge 32 ]; then
    print_status "Generated key for: livekit (${LIVEKIT_KEY:0:8}...${LIVEKIT_KEY: -8})"
else
    print_error "Failed to parse key for livekit"
    echo "JSON response was:"
    echo "$OUTPUT_JSON"
    exit 1
fi

# Step 3: Create/update auth keys secret in LiveKit namespace
echo -e "\n${BLUE}🔐 Creating/updating auth keys secret in LiveKit namespace...${NC}"

# Check if secret already exists
if kubectl get secret livekit-headscale-auth -n "$LIVEKIT_NAMESPACE" &>/dev/null; then
    kubectl patch secret livekit-headscale-auth -n "$LIVEKIT_NAMESPACE" --type merge -p "{
        \"stringData\": {
            \"livekit-authkey\": \"$LIVEKIT_KEY\"
        }
    }"
    print_status "Updated existing auth keys secret"
else
    kubectl create secret generic livekit-headscale-auth -n "$LIVEKIT_NAMESPACE" \
        --from-literal=livekit-authkey="$LIVEKIT_KEY"
    print_status "Created new auth keys secret"
fi

# Step 4: Create ServiceAccount and RBAC for LiveKit Tailscale
echo -e "\n${BLUE}🔒 Creating RBAC for LiveKit Tailscale sidecar...${NC}"

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: livekit-tailscale
  namespace: $LIVEKIT_NAMESPACE
  labels:
    app: livekit-tailscale
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: $LIVEKIT_NAMESPACE
  name: livekit-tailscale
  labels:
    app: livekit-tailscale
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["events"]
  verbs: ["get", "create", "patch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: livekit-tailscale
  namespace: $LIVEKIT_NAMESPACE
  labels:
    app: livekit-tailscale
subjects:
- kind: ServiceAccount
  name: livekit-tailscale
  namespace: $LIVEKIT_NAMESPACE
roleRef:
  kind: Role
  name: livekit-tailscale
  apiGroup: rbac.authorization.k8s.io
EOF

print_status "Created RBAC resources"

# Step 5: Patch LiveKit deployment with Tailscale sidecar
echo -e "\n${BLUE}🚢 Patching LiveKit deployment with Tailscale sidecar...${NC}"

# Get the LiveKit deployment name
LIVEKIT_DEPLOYMENT=$(kubectl get deployment -n "$LIVEKIT_NAMESPACE" -l "app.kubernetes.io/name=livekit" -o jsonpath='{.items[0].metadata.name}')

if [ -z "$LIVEKIT_DEPLOYMENT" ]; then
    print_error "Could not find LiveKit deployment"
    exit 1
fi

print_status "Found LiveKit deployment: $LIVEKIT_DEPLOYMENT"

# Create patch for adding Tailscale sidecar
cat > /tmp/livekit-tailscale-patch.json <<EOF
{
  "spec": {
    "template": {
      "spec": {
        "serviceAccountName": "livekit-tailscale",
        "containers": [
          {
            "name": "tailscale",
            "image": "ghcr.io/tailscale/tailscale:latest",
            "imagePullPolicy": "IfNotPresent",
            "env": [
              {
                "name": "TS_AUTHKEY",
                "valueFrom": {
                  "secretKeyRef": {
                    "name": "livekit-headscale-auth",
                    "key": "livekit-authkey"
                  }
                }
              },
              {
                "name": "TS_USERSPACE",
                "value": "true"
              },
              {
                "name": "TS_STATE_DIR",
                "value": "/var/lib/tailscale"
              },
              {
                "name": "TS_CONTROL_URL",
                "value": "$HEADSCALE_SERVER"
              },
              {
                "name": "TS_SOCKET",
                "value": "/var/run/tailscale/tailscaled.sock"
              },
              {
                "name": "TS_HOSTNAME",
                "value": "livekit"
              },
              {
                "name": "TS_KUBE_SECRET",
                "value": "tailscale"
              },
              {
                "name": "POD_NAME",
                "valueFrom": {
                  "fieldRef": {
                    "fieldPath": "metadata.name"
                  }
                }
              },
              {
                "name": "POD_UID",
                "valueFrom": {
                  "fieldRef": {
                    "fieldPath": "metadata.uid"
                  }
                }
              }
            ],
            "securityContext": {
              "runAsUser": 0,
              "runAsGroup": 0,
              "allowPrivilegeEscalation": false,
              "capabilities": {
                "drop": ["ALL"],
                "add": ["NET_ADMIN"]
              }
            },
            "volumeMounts": [
              {
                "name": "tailscale-state",
                "mountPath": "/var/lib/tailscale"
              },
              {
                "name": "tailscale-run",
                "mountPath": "/var/run/tailscale"
              }
            ],
            "resources": {
              "requests": {
                "cpu": "50m",
                "memory": "128Mi"
              },
              "limits": {
                "cpu": "200m",
                "memory": "256Mi"
              }
            },
            "command": [
              "/bin/sh",
              "-c",
              "set -e; mkdir -p /var/lib/tailscale /var/run/tailscale; chmod 755 /var/lib/tailscale /var/run/tailscale; tailscaled --socket=/var/run/tailscale/tailscaled.sock --statedir=/var/lib/tailscale --tun=userspace-networking & sleep 5; tailscale up --login-server=\"\${TS_CONTROL_URL}\" --authkey=\"\${TS_AUTHKEY}\" --hostname=\"\${TS_HOSTNAME}\" --accept-routes --accept-dns=true; wait"
            ]
          }
        ],
        "volumes": [
          {
            "name": "tailscale-state",
            "emptyDir": {}
          },
          {
            "name": "tailscale-run",
            "emptyDir": {}
          }
        ]
      }
    }
  }
}
EOF

# Apply the patch
if kubectl patch deployment "$LIVEKIT_DEPLOYMENT" -n "$LIVEKIT_NAMESPACE" --type='strategic' --patch-file=/tmp/livekit-tailscale-patch.json; then
    print_status "Successfully patched LiveKit deployment with Tailscale sidecar"
else
    print_error "Failed to patch LiveKit deployment"
    exit 1
fi

# Clean up temp file
rm -f /tmp/livekit-tailscale-patch.json

# Step 6: Wait for rollout
echo -e "\n${BLUE}⏳ Waiting for LiveKit rollout to complete...${NC}"

if kubectl rollout status deployment/"$LIVEKIT_DEPLOYMENT" -n "$LIVEKIT_NAMESPACE" --timeout=300s; then
    print_status "LiveKit rollout completed successfully"
else
    print_warning "LiveKit rollout is taking longer than expected"
fi

# Step 7: Verify registration
echo -e "\n${BLUE}🔍 Verifying Headscale registration...${NC}"

sleep 10  # Give Tailscale time to register

echo "Registered nodes:"
kubectl -n "$HEADSCALE_NAMESPACE" exec deployment/headscale -c headscale -- headscale nodes list

# Step 8: Display access information
echo -e "\n${GREEN}🎉 LiveKit Tailscale integration completed!${NC}"
echo "========================================="
echo "LiveKit should now be accessible via Tailscale:"
echo ""
echo "• LiveKit Tailscale: https://livekit.tail.ozzu.world"
echo "• LiveKit Standard: https://livekit.ozzu.world (unchanged)"
echo ""
echo "To check LiveKit pod status:"
echo "kubectl get pods -n $LIVEKIT_NAMESPACE"
echo ""
echo "To check Tailscale sidecar logs:"
echo "kubectl logs -n $LIVEKIT_NAMESPACE deployment/$LIVEKIT_DEPLOYMENT -c tailscale"
echo ""
echo "To check Headscale status:"
echo "kubectl -n $HEADSCALE_NAMESPACE exec -it deployment/headscale -c headscale -- headscale nodes list"

print_status "LiveKit Tailscale sidecar deployment completed successfully!"