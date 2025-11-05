# June TTS Service with F5-TTS and Voice Cloning
# Based on CosyVoice dependency management approach

# Use CUDA 12.1 base image for PyTorch 2.x compatibility
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04 AS runtime

# Environment setup
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

# Metadata
LABEL maintainer="ozzuworld <eng.ozzu@icloud.com>"
LABEL version="1.0.0-tts-stable"
LABEL description="June TTS with F5-TTS Voice Cloning"
LABEL service="june-tts"
LABEL framework="f5-tts"

# Install system dependencies (following CosyVoice approach)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3-pip \
    ffmpeg \
    libsndfile1 \
    sox \
    libsox-dev \
    curl \
    wget \
    git \
    build-essential \
    cmake \
    pkg-config \
    unzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic links for Python
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Create app directory and user
RUN useradd -m -u 1001 sttuser
WORKDIR /app
RUN chown -R sttuser:sttuser /app

# Install PyTorch with CUDA 12.1 support first
RUN pip install --no-cache-dir \
    torch==2.2.0 \
    torchaudio==2.2.0 \
    --index-url https://download.pytorch.org/whl/cu121

# Copy requirements and install with extended timeout (CosyVoice approach)
COPY --chown=sttuser:sttuser requirements.txt /app/
RUN pip install --no-cache-dir --default-timeout=3600 -r requirements.txt

# Copy all Python files from the build context
COPY --chown=sttuser:sttuser *.py /app/

# Set up environment
ENV PYTHONPATH=/app
USER sttuser

# Create necessary directories
RUN mkdir -p /app/models /app/cache /app/temp

# TTS Environment Configuration
ENV PORT=8002
ENV LOG_LEVEL=INFO

# F5-TTS Configuration
ENV TTS_MODEL=f5-tts
ENV VOICE_CLONING_ENABLED=true
ENV STREAMING_ENABLED=true
ENV BATCH_SIZE=1

# LiveKit Integration
ENV LIVEKIT_ENABLED=true
ENV LIVEKIT_URL="wss://june-livekit.ozzu.cloud"

EXPOSE 8002

# Health check
HEALTHCHECK --interval=20s --timeout=15s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8002/healthz || exit 1

# Startup command
CMD ["python", "main.py"]