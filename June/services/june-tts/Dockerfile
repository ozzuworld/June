# June TTS Service - Production Dockerfile for Chatterbox TTS
FROM nvidia/cuda:12.1-devel-ubuntu22.04

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_VISIBLE_DEVICES=0
ENV TORCH_CUDA_ARCH_LIST="7.0;7.5;8.0;8.6;8.9;9.0"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3.10-pip \
    python3.10-dev \
    python3.10-distutils \
    build-essential \
    cmake \
    git \
    curl \
    wget \
    # Audio processing libraries
    ffmpeg \
    libsndfile1 \
    libsndfile1-dev \
    libasound2-dev \
    portaudio19-dev \
    # Additional dependencies for compilation
    pkg-config \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create symlink for python
RUN ln -s /usr/bin/python3.10 /usr/bin/python

# Set working directory
WORKDIR /app

# Upgrade pip
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Install PyTorch with CUDA 12.1 support first (compatible with Chatterbox)
RUN python -m pip install --no-cache-dir \
    torch==2.1.2+cu121 \
    torchaudio==2.1.2+cu121 \
    --index-url https://download.pytorch.org/whl/cu121

# Install numpy with compatible version for Chatterbox
RUN python -m pip install --no-cache-dir "numpy>=1.24.0,<2.0"

# Install Chatterbox TTS from source with compatible dependencies
RUN git clone https://github.com/resemble-ai/chatterbox.git /tmp/chatterbox

# Install Chatterbox dependencies manually to avoid conflicts
RUN python -m pip install --no-cache-dir \
    librosa==0.10.1 \
    transformers==4.35.0 \
    diffusers==0.24.0 \
    resemble-perth==1.0.1 \
    conformer==0.3.2 \
    safetensors==0.4.0 \
    accelerate==0.24.1 \
    scipy==1.11.0

# Install Chatterbox TTS from source (no deps to avoid conflicts)
RUN cd /tmp/chatterbox && python -m pip install --no-deps -e .

# Copy requirements and install remaining dependencies
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy the shared module first (dependency)
COPY ../shared /app/shared
RUN cd /app && python -m pip install -e ./shared

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/logs /app/models /app/temp

# Set environment variables for optimal GPU performance
ENV CUDA_LAUNCH_BLOCKING=0
ENV CUDA_CACHE_DISABLE=0
ENV TORCH_CUDNN_V8_API_ENABLED=1
ENV OMP_NUM_THREADS=4
ENV MKL_NUM_THREADS=4

# Chatterbox-specific environment variables
ENV CHATTERBOX_CACHE_DIR=/app/models
ENV CHATTERBOX_DEVICE=cuda
ENV TORCH_HOME=/app/models

# Health check
HEALTHCHECK --interval=30s --timeout=15s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]