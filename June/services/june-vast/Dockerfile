# June vast.ai combined STT+TTS image with isolated venvs and Tailscale
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda \
    PATH=/usr/local/cuda/bin:$PATH \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

# Base system deps (both services) + Tailscale
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip \
    ffmpeg espeak-ng libsndfile1 libportaudio2 \
    ca-certificates curl iptables iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Install Tailscale (inside container)
RUN curl -fsSL https://tailscale.com/install.sh | sh

WORKDIR /app

# Create separate virtualenvs to avoid dependency conflicts
RUN python3.10 -m venv /venv-stt && python3.10 -m venv /venv-tts

# Copy requirements
COPY June/services/june-stt/requirements.txt /tmp/stt-requirements.txt
COPY June/services/june-tts/requirements.txt /tmp/tts-requirements.txt

# STT deps (torch 2.1.2 cu118)
RUN /venv-stt/bin/pip install --upgrade pip setuptools wheel && \
    /venv-stt/bin/pip install "numpy<2.0" && \
    /venv-stt/bin/pip install torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 \
      --index-url https://download.pytorch.org/whl/cu118 && \
    /venv-stt/bin/pip install -r /tmp/stt-requirements.txt && \
    rm -rf /root/.cache

# TTS deps (torch 2.2.2 cu118)
RUN /venv-tts/bin/pip install --upgrade pip setuptools wheel && \
    /venv-tts/bin/pip install "numpy<2.0" && \
    /venv-tts/bin/pip install torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 \
      --index-url https://download.pytorch.org/whl/cu118 && \
    /venv-tts/bin/pip install -r /tmp/tts-requirements.txt && \
    rm -rf /root/.cache

# Copy application code
COPY June/services/june-stt/ /app/stt/
COPY June/services/june-tts/ /app/tts/

# Runtime env
ENV TTS_CACHE_PATH=/app/cache \
    TTS_HOME=/app/models \
    WHISPER_CACHE_DIR=/app/models \
    COQUI_TOS_AGREED=1 \
    STT_PORT=8001 \
    TTS_PORT=8000

# Expose service ports
EXPOSE 8000 8001

# Add entrypoint script that starts tailscale and both services
COPY June/services/june-vast/start-both.sh /app/start-both.sh
RUN chmod +x /app/start-both.sh

ENTRYPOINT ["/app/start-both.sh"]
