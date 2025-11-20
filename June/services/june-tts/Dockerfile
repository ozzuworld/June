# Dockerfile for June TTS Service - XTTS v2 (Production Optimized)
#
# Features:
# - DeepSpeed acceleration (2-3x speedup)
# - Latent caching (40-60% faster for repeated voices)
# - Result caching for duplicate requests
# - Low VRAM mode support
# - Full multilingual support including Japanese
# - Streaming inference (<200ms latency)
#
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda-12.1
ENV HF_HOME=/app/.cache/huggingface

# GPU optimization settings (Production-tuned)
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512,expandable_segments:True
ENV CUDA_LAUNCH_BLOCKING=0
ENV TORCH_CUDNN_V8_API_ENABLED=1

# XTTS v2 settings
ENV XTTS_MODEL=tts_models/multilingual/multi-dataset/xtts_v2
ENV WARMUP_ON_STARTUP=1
ENV COQUI_TOS_AGREED=1

# Performance Optimizations (ENABLED by default for production)
ENV USE_DEEPSPEED=1
ENV LOW_VRAM_MODE=0
ENV STREAMING_MODE=1
ENV STREAMING_MODE_IMPROVE=0

# Caching Configuration
ENV ENABLE_RESULT_CACHE=1
ENV CACHE_MAX_SIZE_MB=500
ENV LATENT_CACHE_SIZE=100

# Audio Quality Settings
ENV MIN_REFERENCE_DURATION=3.0
ENV MAX_REFERENCE_DURATION=15.0
ENV TARGET_SAMPLE_RATE=22050

# Install system dependencies and add deadsnakes PPA for Python 3.11
RUN apt-get update && apt-get install -y \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update \
    && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3.11-venv \
    build-essential \
    gcc \
    g++ \
    git \
    ffmpeg \
    libsndfile1 \
    libsox-dev \
    portaudio19-dev \
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Install pip for Python 3.11
RUN curl -sS https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3.11 get-pip.py && \
    rm get-pip.py && \
    python3.11 -m pip install --upgrade pip setuptools wheel

# Install PyTorch 2.4.0+ with CUDA 12.1 support
RUN python3.11 -m pip install \
    torch==2.4.0 \
    torchvision==0.19.0 \
    torchaudio==2.4.0 \
    --index-url https://download.pytorch.org/whl/cu121

# Install Coqui TTS with XTTS v2
RUN python3.11 -m pip install \
    "coqui-tts>=0.22.0" \
    "numpy<2.0.0" \
    "soundfile>=0.12.1" \
    "librosa>=0.10.1" \
    "scipy>=1.11.4"

# Install Japanese language support for XTTS v2
RUN python3.11 -m pip install \
    "cutlet>=0.3.0" \
    "mecab-python3>=1.0.6" \
    "unidic-lite>=1.0.8"

# Install DeepSpeed for faster inference (optional but recommended)
RUN python3.11 -m pip install deepspeed==0.10.3

# Install FastAPI and server dependencies
RUN python3.11 -m pip install \
    "fastapi==0.104.1" \
    "uvicorn[standard]==0.24.0" \
    "pydantic==2.5.0" \
    "httpx==0.25.0" \
    python-multipart \
    sse-starlette

# Install LiveKit Python SDK with compatible protobuf
RUN python3.11 -m pip install "protobuf>=4.21.0,<5.0.0" livekit==0.11.1

# Install PostgreSQL client
RUN python3.11 -m pip install asyncpg

# Install Hugging Face CLI for model downloads
RUN python3.11 -m pip install "huggingface-hub[cli]"

# Create app directory
WORKDIR /app

# Copy application code
COPY app/main.py /app/main.py
COPY app/start.sh /app/start.sh

# Create directories for voices and cache
RUN mkdir -p /app/voices /app/.cache/huggingface

# Make start script executable
RUN chmod +x /app/start.sh

# Pre-download XTTS v2 model (RECOMMENDED for production - speeds up startup)
# This increases image size by ~2GB but eliminates 30-60s model download on first start
# Uncomment for production deployments:
# RUN python3.11 -c "from TTS.api import TTS; TTS('tts_models/multilingual/multi-dataset/xtts_v2', gpu=False)"

# Expose port (8000 for our API)
EXPOSE 8000

# Health check (extended start-period for model download + warmup with Japanese)
# With WARMUP_ON_STARTUP=1, expects English + Japanese warmup (adds ~30s)
HEALTHCHECK --interval=30s --timeout=15s --start-period=360s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Override NVIDIA entrypoint and run start script directly
ENTRYPOINT []
CMD ["/bin/bash", "/app/start.sh"]
