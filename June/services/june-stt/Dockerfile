# June/services/june-stt/Dockerfile - Production external deployment
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1

# Install system dependencies for Whisper and audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Create directories for caching and models
RUN mkdir -p /app/models /app/cache/huggingface /app/cache/whisper /app/logs

# Install PyTorch (CPU version - change to GPU if needed)
# For GPU: use --index-url https://download.pytorch.org/whl/cu121
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy shared authentication module
COPY shared/ ./shared/
RUN pip install -e ./shared/

# Copy application code and environment file
COPY app.py .
COPY orchestrator_client.py .
COPY .env .

# Create non-root user for security
RUN useradd -m -u 1001 appuser && \
    mkdir -p /tmp && \
    chmod 755 /tmp && \
    chown -R appuser:appuser /app /tmp

USER appuser

# Set environment variables for caching
ENV WHISPER_CACHE_DIR=/app/cache/whisper
ENV HF_HOME=/app/cache/huggingface
ENV TORCH_HOME=/app/cache/torch

# Health check with proper timeout for external deployment
HEALTHCHECK --interval=30s --timeout=15s --start-period=120s --retries=5 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Expose port
# Expose port
EXPOSE 8080

# Add startup script for better logging and error handling
COPY --chown=appuser:appuser <<'EOF' /app/start.sh
#!/bin/bash
set -e

echo "🚀 Starting June STT Service (External Deployment)"
echo "=================================="
echo "Service: june-stt"
echo "Version: 2.0.0"
echo "Port: ${PORT:-8080}"
echo "Host: ${HOST:-0.0.0.0}"
echo "External URL: ${EXTERNAL_STT_URL:-not_configured}"
echo "Orchestrator: ${ORCHESTRATOR_URL:-not_configured}"
echo "Keycloak: ${KEYCLOAK_URL:-not_configured}"
echo "=================================="

# Check required environment variables
if [ -z "$KEYCLOAK_URL" ] || [ -z "$KEYCLOAK_CLIENT_ID" ] || [ -z "$KEYCLOAK_CLIENT_SECRET" ]; then
    echo "❌ Missing required Keycloak configuration"
    echo "Required: KEYCLOAK_URL, KEYCLOAK_CLIENT_ID, KEYCLOAK_CLIENT_SECRET"
    exit 1
fi

# Start the application
exec uvicorn app:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8080}" \
    --log-level "${LOG_LEVEL:-info}" \
    --access-log \
    --loop uvloop \
    --http httptools
EOF

RUN chmod +x /app/start.sh

# Use the startup script
CMD ["/app/start.sh"]