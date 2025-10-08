# Multi-stage build for optimal image size
FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 as builder

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3.10-dev \
    python3-pip \
    git \
    wget \
    curl \
    build-essential \
    cmake \
    pkg-config \
    libsndfile1-dev \
    libportaudio2 \
    libportaudio-dev \
    ffmpeg \
    espeak-ng \
    espeak-ng-data \
    libespeak-ng-dev \
    mecab \
    libmecab-dev \
    mecab-ipadic-utf8 \
    libffi-dev \
    rustc \
    cargo \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic links for python
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# Upgrade pip and install build tools
RUN python -m pip install --upgrade pip setuptools wheel

# Install PyTorch with CUDA 11.8 support
RUN pip install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu118

# Install Coqui TTS with all features
RUN pip install TTS[all,server]==0.27.0

# Install additional voice processing libraries
RUN pip install \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    librosa==0.10.1 \
    soundfile==0.12.1 \
    pydub==0.25.1 \
    numpy==1.24.3 \
    scipy==1.11.3 \
    Pillow==10.0.1 \
    requests==2.31.0 \
    pydantic==2.5.0 \
    aiofiles==23.2.1 \
    python-multipart==0.0.6

# Runtime stage
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    ffmpeg \
    espeak-ng \
    espeak-ng-data \
    libsndfile1 \
    libportaudio2 \
    mecab \
    mecab-ipadic-utf8 \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic links for python
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create app directory and user
RUN useradd -m -u 1001 ttsuser
WORKDIR /app
RUN chown -R ttsuser:ttsuser /app

# Copy application code
COPY --chown=ttsuser:ttsuser . /app/

# Switch to non-root user
USER ttsuser

# Create directories for models and voices
RUN mkdir -p /app/models /app/voices /app/cache

# Set TTS environment variables
ENV TTS_CACHE_PATH=/app/cache
ENV TTS_HOME=/app/models

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start command
CMD ["python", "main.py"]
