#!/bin/bash
# Resource Usage Analysis Script
# Diagnoses CPU and memory constraints in Kubernetes cluster

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; }

echo "============================================================"
echo "Kubernetes Cluster Resource Analysis"
echo "============================================================"
echo ""

# 1. Node Capacity
log "1. Node Capacity and Allocatable Resources"
echo ""
kubectl get nodes -o custom-columns=\
NAME:.metadata.name,\
CPU_CAPACITY:.status.capacity.cpu,\
MEM_CAPACITY:.status.capacity.memory,\
CPU_ALLOCATABLE:.status.allocatable.cpu,\
MEM_ALLOCATABLE:.status.allocatable.memory
echo ""

# 2. Allocated Resources Summary
log "2. Allocated Resources on Node"
echo ""
kubectl describe nodes | grep -A 7 "Allocated resources:" | head -20
echo ""

# 3. All Pods Resource Requests/Limits
log "3. All Pods CPU and Memory Requests/Limits"
echo ""
kubectl get pods --all-namespaces -o custom-columns=\
NAMESPACE:.metadata.namespace,\
NAME:.metadata.name,\
CPU_REQ:.spec.containers[*].resources.requests.cpu,\
CPU_LIM:.spec.containers[*].resources.limits.cpu,\
MEM_REQ:.spec.containers[*].resources.requests.memory,\
MEM_LIM:.spec.containers[*].resources.limits.memory,\
STATUS:.status.phase
echo ""

# 4. Pods that are pending
log "4. Pending Pods (Not Scheduled)"
echo ""
PENDING=$(kubectl get pods --all-namespaces --field-selector=status.phase=Pending -o custom-columns=\
NAMESPACE:.metadata.namespace,\
NAME:.metadata.name,\
REASON:.status.conditions[?(@.type==\"PodScheduled\")].message 2>/dev/null || echo "")

if [ -z "$PENDING" ] || [ "$PENDING" = "" ]; then
    success "No pending pods"
else
    echo "$PENDING"
fi
echo ""

# 5. Calculate total requested CPU
log "5. Total CPU Requests by Namespace"
echo ""
for ns in $(kubectl get namespaces -o jsonpath='{.items[*].metadata.name}'); do
    total_cpu=$(kubectl get pods -n $ns -o json 2>/dev/null | \
        jq -r '[.items[].spec.containers[].resources.requests.cpu // "0m" |
        if endswith("m") then .[:-1] | tonumber / 1000 else tonumber end] | add // 0' 2>/dev/null || echo "0")

    if [ "$total_cpu" != "0" ] && [ ! -z "$total_cpu" ]; then
        printf "  %-20s %s CPU cores\n" "$ns:" "$total_cpu"
    fi
done
echo ""

# 6. Top CPU consumers
log "6. Top 10 CPU Request Consumers"
echo ""
kubectl get pods --all-namespaces -o json | \
jq -r '.items[] |
select(.spec.containers[0].resources.requests.cpu != null) |
{
    namespace: .metadata.namespace,
    name: .metadata.name,
    cpu: (.spec.containers[0].resources.requests.cpu // "0m" |
        if endswith("m") then .[:-1] | tonumber else (tonumber * 1000) end)
} |
[.namespace, .name, .cpu] |
@tsv' | \
sort -t $'\t' -k3 -rn | \
head -10 | \
awk '{printf "  %-20s %-40s %6sm\n", $1, $2, $3}'
echo ""

# 7. Actual usage (if metrics-server available)
log "7. Actual Node Resource Usage (requires metrics-server)"
echo ""
if kubectl top nodes 2>/dev/null; then
    echo ""
    log "7b. Actual Pod Resource Usage"
    echo ""
    kubectl top pods --all-namespaces --sort-by=cpu 2>/dev/null | head -15
else
    warn "Metrics server not installed - cannot show actual usage"
    warn "Install with: kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml"
fi
echo ""

# 8. Resource pressure events
log "8. Recent Resource-Related Events"
echo ""
kubectl get events --all-namespaces --sort-by='.lastTimestamp' | \
grep -E "FailedScheduling|Insufficient|OOMKilled|Evicted" | tail -10 || \
success "No recent resource pressure events"
echo ""

# 9. Recommendations
log "9. Analysis and Recommendations"
echo ""

# Get node CPU capacity
NODE_CPU=$(kubectl get nodes -o jsonpath='{.items[0].status.capacity.cpu}')
NODE_MEM=$(kubectl get nodes -o jsonpath='{.items[0].status.capacity.memory}')

# Get total requested
TOTAL_CPU_REQUESTED=$(kubectl get pods --all-namespaces -o json | \
    jq -r '[.items[].spec.containers[].resources.requests.cpu // "0m" |
    if endswith("m") then .[:-1] | tonumber / 1000 else tonumber end] | add // 0' 2>/dev/null || echo "0")

echo "Node Capacity: ${NODE_CPU} CPU cores, ${NODE_MEM} memory"
echo "Total CPU Requested: ${TOTAL_CPU_REQUESTED} cores"
echo ""

# Calculate percentage
if [ "$NODE_CPU" != "" ] && [ "$TOTAL_CPU_REQUESTED" != "0" ]; then
    PERCENT=$(echo "scale=2; ($TOTAL_CPU_REQUESTED / $NODE_CPU) * 100" | bc -l 2>/dev/null || echo "N/A")
    echo "CPU Request Utilization: ${PERCENT}%"
    echo ""

    if (( $(echo "$PERCENT > 90" | bc -l 2>/dev/null || echo 0) )); then
        error "CRITICAL: Over 90% of CPU capacity is requested!"
        echo "  Recommendations:"
        echo "  1. Reduce CPU requests for non-critical workloads"
        echo "  2. Scale down replicas for some services"
        echo "  3. Consider adding more nodes to the cluster"
        echo "  4. Review and optimize resource requests"
    elif (( $(echo "$PERCENT > 70" | bc -l 2>/dev/null || echo 0) )); then
        warn "WARNING: Over 70% of CPU capacity is requested"
        echo "  Recommendations:"
        echo "  1. Review resource requests - some may be over-provisioned"
        echo "  2. Consider reducing limits for bursty workloads"
        echo "  3. Plan for cluster expansion if adding more services"
    else
        success "CPU allocation is healthy (${PERCENT}%)"
    fi
fi
echo ""

echo "============================================================"
echo "Resource Analysis Complete"
echo "============================================================"
