#!/bin/bash
# Fixed rebuild script for orchestrator

echo "🔨 Rebuilding orchestrator with fixed Dockerfile..."

cd June/services/june-orchestrator

# 1. Backup original Dockerfile
cp Dockerfile Dockerfile.backup

# 2. Create fixed Dockerfile
cat > Dockerfile << 'EOF'
FROM python:3.11-slim
WORKDIR /app

# Copy shared auth module directly (without pip install)
COPY ../shared /app/shared

# Copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Set Python path to include shared module
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["sh","-c","uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
EOF

echo "✅ Updated Dockerfile"

# 3. Ensure google-generativeai is in requirements.txt
if ! grep -q "google-generativeai" requirements.txt; then
    echo "google-generativeai>=0.3.0" >> requirements.txt
    echo "✅ Added google-generativeai to requirements.txt"
fi

# 4. Build new container image
echo "🐳 Building new container image..."
docker build -t us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:$(date +%s) .
docker tag us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:$(date +%s) us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:latest

# 5. Push to registry
echo "📤 Pushing to registry..."
docker push us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-orchestrator:latest

# 6. Force restart deployment
echo "🔄 Restarting deployment..."
kubectl rollout restart deployment/june-orchestrator -n june-services

# 7. Wait for rollout
echo "⏳ Waiting for rollout to complete..."
kubectl rollout status deployment/june-orchestrator -n june-services --timeout=300s

echo "✅ Rebuild complete! Check logs:"
echo "kubectl logs deployment/june-orchestrator -n june-services -f"