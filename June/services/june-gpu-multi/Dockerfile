# Multi-service container with both STT and TTS for Vast.ai GPU sharing
FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies for both services + Tailscale
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3-pip \
    git \
    build-essential \
    cmake \
    pkg-config \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libavdevice-dev \
    libavfilter-dev \
    libswscale-dev \
    libswresample-dev \
    libsndfile1-dev \
    portaudio19-dev \
    ffmpeg \
    espeak-ng \
    curl \
    supervisor \
    dos2unix \
    ca-certificates \
    gnupg \
    lsb-release \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Install compatible NumPy FIRST (critical for PyTorch compatibility)
RUN pip install --no-cache-dir "numpy<2.0"

# Install PyTorch 2.2.2 with CUDA 11.8 support (compatible with both services)
RUN pip install --no-cache-dir torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 \
    --index-url https://download.pytorch.org/whl/cu118

WORKDIR /app

# Copy and install requirements for both services
COPY stt-requirements.txt /app/stt-requirements.txt
COPY tts-requirements.txt /app/tts-requirements.txt
RUN pip install --no-cache-dir -r /app/stt-requirements.txt
RUN pip install --no-cache-dir -r /app/tts-requirements.txt

RUN rm -rf /tmp/* /var/tmp/* /root/.cache

# Runtime stage
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

# Install runtime dependencies INCLUDING Tailscale
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    ffmpeg \
    espeak-ng \
    libsndfile1 \
    libportaudio2 \
    curl \
    supervisor \
    dos2unix \
    ca-certificates \
    gnupg \
    lsb-release \
    iptables \
    iproute2 \
    && curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.noarmor.gpg | tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null \
    && curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.tailscale-keyring.list | tee /etc/apt/sources.list.d/tailscale.list \
    && apt-get update \
    && apt-get install -y tailscale \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create app directory and user
RUN useradd -m -u 1001 juneuser
WORKDIR /app
RUN chown -R juneuser:juneuser /app

# Create service directories + Tailscale state directory
RUN mkdir -p /app/stt /app/tts /app/models /app/cache /etc/supervisor/conf.d /var/log/supervisor /var/run \
    /var/lib/tailscale /var/run/tailscale
RUN chown -R juneuser:juneuser /app /var/log/supervisor /var/run /var/lib/tailscale /var/run/tailscale

# Copy STT service files
COPY --chown=juneuser:juneuser stt/ /app/stt/

# Copy TTS service files 
COPY --chown=juneuser:juneuser tts/ /app/tts/

# Copy supervisor configuration
COPY --chown=juneuser:juneuser supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy startup script
COPY --chown=juneuser:juneuser start-services.sh /app/start-services.sh

# Copy Tailscale connection script
COPY --chown=juneuser:juneuser tailscale-connect.sh /app/tailscale-connect.sh

# 🔧 FIX: Convert line endings to Unix format for all shell scripts
RUN dos2unix /app/start-services.sh /app/tailscale-connect.sh && \
    chmod +x /app/start-services.sh /app/tailscale-connect.sh

# Ensure module import works for both services
ENV PYTHONPATH=/app:/app/stt:/app/tts

# Environment variables for both services
ENV STT_PORT=8001
ENV TTS_PORT=8000
ENV WHISPER_CACHE_DIR=/app/models
ENV WHISPER_DEVICE=cuda
ENV WHISPER_COMPUTE_TYPE=float16
ENV TTS_CACHE_PATH=/app/cache
ENV TTS_HOME=/app/models
ENV COQUI_TOS_AGREED=1
ENV CUDA_VISIBLE_DEVICES=0

# Don't switch to juneuser here - supervisor needs root to create socket
# The services will still run as juneuser (configured in supervisord.conf)

# Expose both service ports
EXPOSE 8000 8001

# 🔧 IMPROVED: More realistic health check timing for GPU model loading
HEALTHCHECK --interval=30s --timeout=60s --start-period=180s --retries=3 \
    CMD curl -f http://localhost:8000/healthz && curl -f http://localhost:8001/healthz || exit 1

# Run both services with supervisor
CMD ["/app/start-services.sh"]