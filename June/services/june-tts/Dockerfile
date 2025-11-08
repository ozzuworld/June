# Dockerfile for XTTS v2 TTS Service with GPU Support (CUDA 11.8)
# Based on official Coqui XTTS streaming server

FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV COQUI_TOS_AGREED=1
ENV CUDA_HOME=/usr/local/cuda-11.8

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    python3-dev \
    git \
    ffmpeg \
    libsndfile1 \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN python3 -m pip install --upgrade pip

# Install PyTorch 2.1.0 with CUDA 11.8 support
RUN pip3 install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu118

# Install TTS and XTTS v2 dependencies
RUN pip3 install TTS==0.22.0

# Install FastAPI and server dependencies
RUN pip3 install \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    httpx==0.25.0 \
    numpy==1.24.3 \
    scipy==1.11.4 \
    soundfile==0.12.1 \
    librosa==0.10.1 \
    ormsgpack==1.4.0

# Install LiveKit Python SDK for audio publishing
RUN pip3 install livekit==0.11.0

# Create app directory
WORKDIR /app

# Copy application code
COPY app/ /app/

# Create directories for models and references
RUN mkdir -p /app/models /app/references

# Pre-download XTTS v2 model WITHOUT GPU (CPU mode for build)
# This caches the model so it doesn't need to download at runtime
RUN python3 -c "from TTS.api import TTS; TTS('tts_models/multilingual/multi-dataset/xtts_v2', gpu=False)"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]