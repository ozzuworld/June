# Dockerfile for Chatterbox TTS Service with GPU Support
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda-12.1
ENV HF_HOME=/app/.cache/huggingface

# GPU optimization settings
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512,expandable_segments:True
ENV CUDA_LAUNCH_BLOCKING=0
ENV TORCH_CUDNN_V8_API_ENABLED=1

# Chatterbox settings
ENV USE_MULTILINGUAL=1
ENV WARMUP_ON_STARTUP=1
ENV MAX_WORKERS=2

# Phase 1 Optimization settings (legacy - FP16 handled by vLLM)
ENV USE_FP16=0
ENV USE_TORCH_COMPILE=0
ENV TORCH_COMPILE_MODE=reduce-overhead
ENV TORCHINDUCTOR_CACHE_DIR=/app/.cache/torch_compile

# vLLM Optimization settings (4-10x speedup)
ENV VLLM_GPU_MEMORY_UTILIZATION=0.6
ENV VLLM_MAX_MODEL_LEN=1000
ENV VLLM_ENFORCE_EAGER=1
ENV CHATTERBOX_CFG_SCALE=0.3

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

# Install PyTorch 2.4.0 with CUDA 12.1 (compatible with latest transformers)
RUN python3.11 -m pip install \
    torch==2.4.0 \
    torchvision==0.19.0 \
    torchaudio==2.4.0 \
    --index-url https://download.pytorch.org/whl/cu121

# Install vLLM 0.9.2 (required for chatterbox-vllm)
# This provides 4-10x speedup over original chatterbox implementation
RUN python3.11 -m pip install vllm==0.9.2

# Install transformers and tokenizers (vLLM compatible version)
RUN python3.11 -m pip install "transformers>=4.36.0,<4.54.0" tokenizers

# Install core ML dependencies (required for Chatterbox vLLM inference)
RUN python3.11 -m pip install \
    "numpy<2" \
    librosa \
    s3tokenizer \
    diffusers \
    safetensors \
    spacy-pkuseg \
    pykakasi \
    resemble-perth \
    conformer \
    accelerate>=0.25.0 \
    einops>=0.7.0 \
    vector-quantize-pytorch>=1.14.0 \
    natsort>=8.4.0 \
    soundfile>=0.12.1 \
    scipy>=1.11.4 \
    loguru>=0.7.0 \
    hydra-core>=1.3.2 \
    omegaconf>=2.3.0 \
    peft \
    "llvmlite>=0.44.0"

# Install Chatterbox TTS vLLM port WITHOUT dependencies (to prevent vLLM upgrade)
# The package incorrectly pins vllm==0.10.0 even though it was built for 0.9.2
RUN python3.11 -m pip install --no-deps chatterbox-vllm==0.1.3

# Ensure vLLM stays at 0.9.2 (verify it wasn't upgraded)
RUN python3.11 -m pip install vllm==0.9.2

# Install FastAPI and server dependencies
RUN python3.11 -m pip install \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    httpx==0.25.0 \
    asyncpg \
    python-multipart

# Install LiveKit Python SDK with compatible protobuf
RUN python3.11 -m pip install "protobuf>=4.21.0,<5.0.0" livekit==0.11.1

# Install Hugging Face CLI for model downloads
RUN python3.11 -m pip install huggingface-hub[cli]

# CRITICAL: Use .pth file for automatic tokenizer registration
# .pth files with "import" statements are executed by Python's site module at startup
# This is more reliable than sitecustomize.py for multiprocessing spawn mode
COPY chatterbox_init.pth /usr/local/lib/python3.11/site-packages/chatterbox_init.pth
COPY sitecustomize.py /usr/local/lib/python3.11/site-packages/sitecustomize.py

# Create app directory
WORKDIR /app

# Copy application code
COPY app/ /app/

# Create directories for voices, references, and cache
RUN mkdir -p /app/voices /app/references /app/.cache/torch_compile /app/.cache/huggingface

# Create vLLM model directories (required for symlink creation)
RUN mkdir -p /app/t3-model /app/s3gen-model

# Make start script executable
RUN chmod +x /app/start.sh

# Expose port (8000 for our API)
EXPOSE 8000

# Health check (extended start-period for model download + warmup)
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run via start script
CMD ["/app/start.sh"]