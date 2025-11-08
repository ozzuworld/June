# Dockerfile for XTTS v2 TTS Service with GPU Support
# FINAL FIX: Skip model download during build, download at runtime instead

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

# Install PyTorch 2.0.1 with CUDA 11.8 (avoid 2.6+ which has weights_only issues)
RUN pip3 install \
    torch==2.0.1+cu118 \
    torchvision==0.15.2+cu118 \
    torchaudio==2.0.2+cu118 \
    --index-url https://download.pytorch.org/whl/cu118

# Install transformers first (compatible version)
RUN pip3 install transformers==4.33.0

# Install TTS 0.22.0
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

# Install LiveKit Python SDK
RUN pip3 install livekit==0.11.0

# Create app directory
WORKDIR /app

# Copy application code
COPY app/ /app/

# Create directories for models and references
RUN mkdir -p /app/models /app/references

# REMOVED: Model download during build (causes PyTorch 2.6 weights_only issues)
# Model will auto-download on first inference at runtime instead

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
