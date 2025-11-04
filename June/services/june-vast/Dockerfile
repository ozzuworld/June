# June vast.ai combined STT+TTS image with official faster-whisper GPU setup
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda \
    PATH=/usr/local/cuda/bin:$PATH

# Base system deps (both services)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip \
    ffmpeg espeak-ng libsndfile1 libportaudio2 \
    ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create separate virtualenvs to avoid dependency conflicts
RUN python3.10 -m venv /venv-stt && python3.10 -m venv /venv-tts

# Copy shared module first (required by both services)
COPY June/services/shared/ /app/shared/

# Install shared module in both virtual environments
RUN /venv-stt/bin/pip install --upgrade pip setuptools wheel && \
    /venv-stt/bin/pip install -e /app/shared

RUN /venv-tts/bin/pip install --upgrade pip setuptools wheel && \
    /venv-tts/bin/pip install -e /app/shared

# Copy requirements
COPY June/services/june-stt/requirements.txt /tmp/stt-requirements.txt
COPY June/services/june-tts/requirements.txt /tmp/tts-requirements.txt

# STT deps with official faster-whisper GPU libraries
RUN /venv-stt/bin/pip install "numpy<2.0" && \
    /venv-stt/bin/pip install torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 \
      --index-url https://download.pytorch.org/whl/cu121 && \
    /venv-stt/bin/pip install -r /tmp/stt-requirements.txt && \
    rm -rf /root/.cache

# TTS deps with CUDA 12.3 compatibility and Chatterbox from source
RUN /venv-tts/bin/pip install "numpy<2.0" && \
    /venv-tts/bin/pip install torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 \
      --index-url https://download.pytorch.org/whl/cu121 && \
    # Install Chatterbox from source without deps to avoid numpy pin conflicts
    git clone https://github.com/resemble-ai/chatterbox.git /tmp/chatterbox && \
    /venv-tts/bin/pip install --no-deps -e /tmp/chatterbox && \
    # Install explicit compatible dependencies without forcing numpy downgrade
    /venv-tts/bin/pip install --no-deps s3tokenizer && \
    /venv-tts/bin/pip install \
      librosa==0.11.0 \
      transformers==4.46.3 \
      diffusers==0.29.0 \
      resemble-perth==1.0.1 \
      conformer==0.3.2 \
      safetensors==0.5.3 \
      accelerate==0.24.1 \
      scipy==1.11.0 \
      onnx==1.16.0 && \
    # Install remaining app deps from requirements (excluding chatterbox-tts line)
    /venv-tts/bin/pip install -r /tmp/tts-requirements.txt && \
    rm -rf /root/.cache

# Copy application code
COPY June/services/june-stt/ /app/stt/
COPY June/services/june-tts/ /app/tts/

# Runtime env with CUDA library paths
ENV TTS_CACHE_PATH=/app/cache \
    TTS_HOME=/app/models \
    WHISPER_CACHE_DIR=/app/models \
    COQUI_TOS_AGREED=1 \
    STT_PORT=8001 \
    TTS_PORT=8000 \
    PYTHONPATH=/app

# Expose service ports
EXPOSE 8000 8001

# Add entrypoint script that starts both services
COPY June/services/june-vast/start-both.sh /app/start-both.sh
RUN chmod +x /app/start-both.sh

ENTRYPOINT ["/app/start-both.sh"]