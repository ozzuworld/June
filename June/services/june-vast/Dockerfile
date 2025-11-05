# June vast.ai - Production-ready STT+TTS with Supervisord
FROM nvidia/cuda:12.4.1-cudnn9-devel-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=/usr/local/cuda/bin:$PATH
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

# Install system dependencies + supervisord
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip python3.10-dev \
    ffmpeg sox libsox-dev libsndfile1 libsndfile1-dev \
    ca-certificates curl wget git git-lfs \
    build-essential cmake pkg-config \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Miniconda (for CosyVoice)
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/miniconda && rm /tmp/miniconda.sh
ENV PATH="/opt/miniconda/bin:$PATH"
RUN conda config --system --remove-key channels || true && \
    conda config --system --add channels conda-forge && \
    conda config --system --set channel_priority strict && \
    conda create -n cosyvoice python=3.10 -y && \
    conda run -n cosyvoice conda install -y -c conda-forge pynini==2.1.5 && \
    conda clean -afy

# Create SEPARATE venvs for isolation
RUN python3.10 -m venv /venv-stt && \
    python3.10 -m venv /venv-tts

# Install shared PyTorch stack for STT (let WhisperX handle it)
RUN /venv-stt/bin/pip install --upgrade pip setuptools wheel

# Install shared PyTorch stack for TTS (explicit CUDA 12.4)
RUN /venv-tts/bin/pip install --upgrade pip setuptools wheel && \
    /venv-tts/bin/pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cu124 \
      torch==2.6.0+cu124 \
      torchvision==0.21.0+cu124 \
      torchaudio==2.6.0+cu124

# Shared module
COPY June/services/shared/ /app/shared/
RUN /venv-stt/bin/pip install -e /app/shared && \
    /venv-tts/bin/pip install -e /app/shared

# Copy requirements
COPY June/services/june-stt/requirements.txt /tmp/stt-requirements.txt
COPY June/services/june-tts/requirements.txt /tmp/tts-requirements.txt

# Install STT dependencies
RUN /venv-stt/bin/pip install --no-cache-dir -r /tmp/stt-requirements.txt && \
    rm -rf /root/.cache

# CosyVoice setup
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice && \
    cd /opt/CosyVoice && git submodule update --init --recursive && \
    /venv-tts/bin/pip install --no-cache-dir -r requirements.txt && \
    /venv-tts/bin/pip install --no-cache-dir -r /tmp/tts-requirements.txt && \
    rm -rf /root/.cache

ENV PYTHONPATH="/opt/CosyVoice/third_party/Matcha-TTS:/opt/CosyVoice:/opt/miniconda/envs/cosyvoice/lib/python3.10/site-packages"

# Copy application code
COPY June/services/june-stt/ /app/stt/
COPY June/services/june-tts/ /app/tts/

# Create log directories
RUN mkdir -p /var/log/supervisor /app/logs /app/models /app/pretrained_models /app/cache

# Supervisord configuration (NEW)
COPY June/services/june-vast/supervisord.conf /etc/supervisor/conf.d/june.conf

# Health check script (NEW)
COPY June/services/june-vast/healthcheck.sh /app/healthcheck.sh
RUN chmod +x /app/healthcheck.sh

# Environment defaults
ENV WHISPER_CACHE_DIR=/app/models \
    MODEL_DIR=/app/pretrained_models \
    COSYVOICE_MODEL=CosyVoice2-0.5B \
    STT_PORT=8001 \
    TTS_PORT=8000 \
    ORCHESTRATOR_URL=https://api.ozzu.world

EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD /app/healthcheck.sh

# Start supervisord instead of bash script
CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]