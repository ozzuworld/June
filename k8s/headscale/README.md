# Headscale admin helper script for Kubernetes
# Usage:
#   kubectl -n headscale exec -it deploy/headscale -- headscale <args>
# Examples:
#   kubectl -n headscale exec -it deploy/headscale -- headscale users create ozzu
#   kubectl -n headscale exec -it deploy/headscale -- headscale preauthkeys create --user ozzu --reusable --ephemeral

