# File: June/services/june-tts/Dockerfile
# Official Chatterbox TTS Installation Method

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    ffmpeg \
    libsndfile1 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Chatterbox TTS using the OFFICIAL method
RUN git clone https://github.com/resemble-ai/chatterbox.git /tmp/chatterbox && \
    cd /tmp/chatterbox && \
    pip install -e . && \
    cd / && \
    rm -rf /tmp/chatterbox

# Install additional required dependencies
RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    PyJWT[crypto]==2.8.0 \
    cryptography==41.0.7 \
    httpx==0.27.0 \
    python-multipart==0.0.9 \
    aiofiles==23.2.0

# Copy application code
COPY . .

# Create directories
RUN mkdir -p /app/models /app/voices /app/cache

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Expose port
EXPOSE 8080

# Start the service
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]