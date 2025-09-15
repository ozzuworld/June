# File: June/services/june-tts/Dockerfile
# Working Chatterbox TTS using travisvn/chatterbox-tts-api

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

# Clone the working chatterbox-tts-api implementation
RUN git clone https://github.com/travisvn/chatterbox-tts-api.git /tmp/chatterbox-api && \
    cp -r /tmp/chatterbox-api/* /app/ && \
    rm -rf /tmp/chatterbox-api

# Install dependencies from the working implementation
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy our custom integration layer
COPY app.py /app/june_tts_wrapper.py
COPY shared/ /app/shared/

# Create directories for models and cache
RUN mkdir -p /app/models /app/voices /app/cache

# Set environment variables for the API
ENV HOST=0.0.0.0 \
    PORT=8080 \
    DEVICE=cpu \
    LOG_LEVEL=INFO \
    EXAGGERATION=0.5 \
    CFG_WEIGHT=0.5 \
    TEMPERATURE=1.0

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

# Start both the chatterbox API and our wrapper
CMD ["python", "june_tts_wrapper.py"]