# Virtual Kubelet Vast.ai Provider Makefile

REGISTRY ?= ozzuworld
IMAGE_NAME = virtual-kubelet-vast
TAG ?= latest
FULL_IMAGE = $(REGISTRY)/$(IMAGE_NAME):$(TAG)

.PHONY: help build test docker push deploy clean

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build the Go binary locally
	@echo "Building Virtual Kubelet Vast.ai provider..."
	CGO_ENABLED=0 GOOS=linux go build \
		-ldflags='-s -w' \
		-o bin/virtual-kubelet-vast \
		./cmd/vk-vast
	@echo "Binary built: bin/virtual-kubelet-vast"

test: ## Run tests
	@echo "Running tests..."
	go test -v ./...

docker: ## Build Docker image
	@echo "Building Docker image: $(FULL_IMAGE)"
	docker build -t $(FULL_IMAGE) .
	@echo "Docker image built: $(FULL_IMAGE)"

push: docker ## Build and push Docker image
	@echo "Pushing Docker image: $(FULL_IMAGE)"
	docker push $(FULL_IMAGE)
	@echo "Docker image pushed: $(FULL_IMAGE)"

deploy: ## Deploy to Kubernetes (requires image to be pushed)
	@echo "Updating Kubernetes deployment with image: $(FULL_IMAGE)"
	kubectl patch deployment virtual-kubelet-vast -n kube-system -p '{
		"spec": {
			"template": {
				"spec": {
					"containers": [{
						"name": "virtual-kubelet",
						"image": "$(FULL_IMAGE)"
					}]
				}
			}
		}
	}'
	@echo "Deployment updated. Check status with: kubectl -n kube-system get pods -l app=virtual-kubelet-vast"

clean: ## Clean build artifacts
	@echo "Cleaning build artifacts..."
	rm -rf bin/
	docker rmi $(FULL_IMAGE) 2>/dev/null || true
	@echo "Clean complete"

# Development helpers
dev-logs: ## Show Virtual Kubelet logs
	kubectl -n kube-system logs -l app=virtual-kubelet-vast -f

dev-status: ## Show deployment status
	@echo "=== Virtual Kubelet Status ==="
	kubectl -n kube-system get pods -l app=virtual-kubelet-vast
	@echo "=== Nodes ==="
	kubectl get nodes
	@echo "=== GPU Pods ==="
	kubectl get pods -l app=june-gpu-services -o wide
	@echo "=== Service Endpoints ==="
	kubectl get endpoints june-stt june-tts

dev-debug: ## Debug Virtual Kubelet issues
	@echo "=== Virtual Kubelet Pod Details ==="
	kubectl -n kube-system describe pods -l app=virtual-kubelet-vast
	@echo "=== Recent Events ==="
	kubectl get events --sort-by='.lastTimestamp' | tail -10

quick-test: build docker ## Quick build and test locally
	@echo "Testing Virtual Kubelet provider locally..."
	@echo "Set these environment variables and run bin/virtual-kubelet-vast:"
	@echo "  export VAST_API_KEY='your_api_key'"
	@echo "  export NODENAME='vast-gpu-node-test'"
	@echo "  export KUBECONFIG='~/.kube/config'"