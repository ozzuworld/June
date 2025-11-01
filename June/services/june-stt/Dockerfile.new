# Enhanced June STT - Using faster-whisper-server as base
# Multi-stage build combining faster-whisper-server optimizations with LiveKit integration

# Stage 1: Get faster-whisper-server functionality
FROM fedirz/faster-whisper-server:latest-cuda AS whisper-base

# Stage 2: Build our enhanced service
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 AS runtime

# Environment setup
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

# Image metadata
LABEL maintainer="ozzuworld <eng.ozzu@icloud.com>"
LABEL version="4.0.0-enhanced"
LABEL description="June STT Enhanced - faster-whisper-server + LiveKit Integration"
LABEL service="june-stt"

# Copy faster-whisper-server Python environment and dependencies
COPY --from=whisper-base /usr/local/lib/python*/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=whisper-base /usr/local/bin /usr/local/bin

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    ffmpeg \
    libsndfile1 \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic links for Python
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# Create app directory and user
RUN useradd -m -u 1001 sttuser
WORKDIR /app
RUN chown -R sttuser:sttuser /app

# Install additional dependencies for LiveKit integration
COPY --chown=sttuser:sttuser requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy enhanced application code
COPY --chown=sttuser:sttuser main.py /app/
COPY --chown=sttuser:sttuser config.py /app/
COPY --chown=sttuser:sttuser whisper_service.py /app/
COPY --chown=sttuser:sttuser livekit_token.py /app/
COPY --chown=sttuser:sttuser orchestrator_client.py /app/
COPY --chown=sttuser:sttuser README.md /app/

# Set up environment
ENV PYTHONPATH=/app
USER sttuser

# Create necessary directories
RUN mkdir -p /app/models /app/cache /app/temp

# Environment configuration
ENV WHISPER_CACHE_DIR=/app/models
ENV PORT=8000
ENV LOG_LEVEL=INFO

# Default Whisper model
ENV WHISPER_MODEL=base
ENV USE_BATCHED_INFERENCE=true
ENV VAD_ENABLED=false

EXPOSE 8000

# Enhanced health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:8000/healthz | grep -q '"status":"healthy"' || exit 1

# Startup command
CMD ["python", "main.py"]
