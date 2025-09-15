# File: June/services/june-tts/Dockerfile
# Chatterbox TTS Service Docker Image

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

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for models, voices, and cache
RUN mkdir -p /app/models /app/voices /app/cache

# Set permissions for any scripts
RUN chmod +x /app/*.py || true

# Health check (extended timeout for model loading)
HEALTHCHECK --interval=30s --timeout=30s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Expose port
EXPOSE 8080

# Start the Chatterbox TTS service
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]