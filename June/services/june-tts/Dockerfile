# Multi-stage build for optimal image size
FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 AS builder

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3-pip \
    git \
    build-essential \
    cmake \
    pkg-config \
    libsndfile1-dev \
    portaudio19-dev \
    ffmpeg \
    espeak-ng \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic links for python
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# Upgrade pip and install essential tools
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Install compatible NumPy FIRST (critical for PyTorch compatibility)
RUN pip install --no-cache-dir "numpy<2.0"

# Install PyTorch 2.1.2 with CUDA 11.8 support
RUN pip install --no-cache-dir torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 \
    --index-url https://download.pytorch.org/whl/cu118

# Use requirements.txt to ensure single source of truth
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Clean up
RUN rm -rf /tmp/* /var/tmp/* /root/.cache

# Runtime stage
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    ffmpeg \
    espeak-ng \
    libsndfile1 \
    libportaudio2 \
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

# Copy application code (only the files that exist)
COPY --chown=ttsuser:ttsuser main.py /app/
COPY --chown=ttsuser:ttsuser config.py /app/
COPY --chown=ttsuser:ttsuser requirements.txt /app/

# Switch to non-root user
USER ttsuser

# Create directories for TTS models and cache
RUN mkdir -p /app/models /app/cache

# Set TTS environment variables
ENV TTS_CACHE_PATH=/app/cache
ENV TTS_HOME=/app/models
ENV COQUI_TOS_AGREED=1
ENV PORT=8000

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Start command
CMD ["python", "main.py"]