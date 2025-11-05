# CosyVoice2 TTS Service - Official Implementation
# Based on official CosyVoice requirements
# Reference: https://github.com/FunAudioLLM/CosyVoice

# Use CUDA 12.1 base for PyTorch 2.2-2.3 compatibility
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

# Environment setup
ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=/usr/local/cuda/bin:$PATH
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

# Metadata
LABEL maintainer="ozzuworld <eng.ozzu@icloud.com>"
LABEL version="1.1.0-cosyvoice2"
LABEL description="June TTS with CosyVoice2-0.5B - Official Method"

# Install system dependencies (official requirements)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-venv \
    python3-pip \
    ffmpeg \
    sox \
    libsox-dev \
    ca-certificates \
    curl \
    wget \
    git \
    git-lfs \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Initialize git-lfs
RUN git lfs install

# Install Miniconda (required for pynini)
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/miniconda && \
    rm /tmp/miniconda.sh

ENV PATH="/opt/miniconda/bin:$PATH"

# Create working directory
WORKDIR /app

# Create Python virtual environment
RUN python3.10 -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install PyTorch with CUDA 12.1 support FIRST (official recommendation)
RUN /venv/bin/pip install --upgrade pip setuptools wheel && \
    /venv/bin/pip install \
    torch==2.2.2 \
    torchaudio==2.2.2 \
    --index-url https://download.pytorch.org/whl/cu121

# Install pynini via conda (REQUIRED by WeTextProcessing)
RUN conda install -y -c conda-forge pynini==2.1.5

# Clone CosyVoice repository with submodules (CRITICAL - must use --recursive)
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice && \
    cd /opt/CosyVoice && \
    git submodule update --init --recursive

# Install CosyVoice dependencies
COPY requirements.txt /tmp/requirements.txt
RUN /venv/bin/pip install -r /tmp/requirements.txt

# Install CosyVoice package
RUN cd /opt/CosyVoice && \
    /venv/bin/pip install --no-deps -e .

# Add Matcha-TTS to Python path (REQUIRED by CosyVoice)
ENV PYTHONPATH="/opt/CosyVoice/third_party/Matcha-TTS:$PYTHONPATH"

# Copy shared module if exists
COPY shared/ /app/shared/ 2>/dev/null || true 
RUN if [ -d /app/shared ]; then /venv/bin/pip install -e /app/shared; fi

# Copy application code
COPY config.py /app/
COPY main.py /app/
COPY livekit_token.py /app/
COPY download_models.py /app/

# Create model directory
RUN mkdir -p /app/pretrained_models

# Set proper permissions
RUN chmod -R 755 /app

# Environment variables
ENV MODEL_DIR=/app/pretrained_models
ENV COSYVOICE_MODEL=CosyVoice2-0.5B
ENV TTS_DEVICE=auto
ENV TTS_FP16=true
ENV TTS_STREAMING=true

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Download models on first run (optional - can be done at build time)
# RUN /venv/bin/python /app/download_models.py

# Startup command
CMD ["/venv/bin/python", "/app/main.py"]