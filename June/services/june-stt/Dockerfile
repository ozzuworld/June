FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive

# ⭐ BAKE IN YOUR CONFIGURATION HERE
ENV SERVICE_NAME=june-stt
ENV PORT=8080
ENV HOST=0.0.0.0

# Keycloak configuration
ENV KEYCLOAK_URL=https://idp.allsafe.world
ENV KEYCLOAK_REALM=allsafe
ENV KEYCLOAK_CLIENT_ID=june-stt
ENV KEYCLOAK_CLIENT_SECRET=gzz55N5XdrMl48UlCNe0Bag5FyoNY0G7
ENV REQUIRED_AUDIENCE=june-stt
ENV JWKS_CACHE_TTL=300

# Orchestrator configuration
ENV ORCHESTRATOR_URL=https://api.allsafe.world
ENV ENABLE_ORCHESTRATOR_NOTIFICATIONS=true
ENV ORCHESTRATOR_WEBHOOK_PATH=/v1/stt/webhook

# Whisper configuration
ENV WHISPER_MODEL=large-v3
ENV WHISPER_DEVICE=auto
ENV WHISPER_CACHE_DIR=/app/models
ENV HF_HOME=/app/cache/huggingface

# CORS configuration
ENV CORS_ALLOW_ORIGINS=https://api.allsafe.world,https://idp.allsafe.world,http://localhost:3000
ENV CORS_ALLOW_METHODS=GET,POST,PUT,DELETE,OPTIONS
ENV CORS_ALLOW_HEADERS=*
ENV CORS_ALLOW_CREDENTIALS=true

# Performance & Limits
ENV MAX_FILE_SIZE_MB=25
ENV MAX_DURATION_MINUTES=30
ENV MAX_CONCURRENT_TRANSCRIPTIONS=3
ENV TRANSCRIPT_RETENTION_HOURS=24
ENV HTTP_TIMEOUT_SECONDS=30
ENV ORCHESTRATOR_TIMEOUT_SECONDS=10

# Logging
ENV LOG_LEVEL=INFO
ENV LOG_FORMAT=json

# Security
ENV RATE_LIMIT_REQUESTS_PER_MINUTE=100
ENV RATE_LIMIT_BURST_SIZE=20
ENV TRUST_PROXY_HEADERS=true
ENV REAL_IP_HEADER=X-Forwarded-For

# Install system dependencies for Whisper and audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    build-essential \
    pkg-config \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Install PyTorch (CPU version)
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared module first (for auth) and install as package
COPY shared/ ./shared/
RUN pip install -e ./shared/

# ⭐ COPY ONLY THE FILES THAT ACTUALLY EXIST
COPY app.py .

# Create non-root user and necessary directories
RUN useradd -m -u 1001 appuser && \
    mkdir -p /tmp /app/models /app/cache/huggingface && \
    chmod 755 /tmp && \
    chown -R appuser:appuser /app /tmp

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Expose port
EXPOSE 8080

# Start the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]