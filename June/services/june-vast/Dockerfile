# June vast.ai combined STT+TTS image with CosyVoice2
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=/usr/local/cuda/bin:$PATH

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip python3.10-dev \
    ffmpeg sox libsox-dev libsndfile1 libsndfile1-dev \
    ca-certificates curl wget git git-lfs \
    build-essential cmake pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/miniconda && \
    rm /tmp/miniconda.sh
ENV PATH="/opt/miniconda/bin:$PATH"

# Configure conda to use only conda-forge
RUN conda config --system --remove-key channels || true && \
    conda config --system --add channels conda-forge && \
    conda config --system --set channel_priority strict

WORKDIR /app

# Create conda environment with Python 3.10 for CosyVoice dependencies
RUN conda create -n cosyvoice python=3.10 -y && \
    conda run -n cosyvoice conda install -y -c conda-forge pynini==2.1.5 && \
    conda clean -afy

# Create separate virtual environments for STT and TTS
RUN python3.10 -m venv /venv-stt && \
    python3.10 -m venv /venv-tts

# Copy shared module
COPY June/services/shared/ /app/shared/

# Install shared module in both environments
RUN if [ -d /app/shared ]; then \
        /venv-stt/bin/pip install --upgrade pip setuptools wheel && \
        /venv-stt/bin/pip install -e /app/shared && \
        /venv-tts/bin/pip install --upgrade pip setuptools wheel && \
        /venv-tts/bin/pip install -e /app/shared; \
    fi

# Copy requirements
COPY June/services/june-stt/requirements.txt /tmp/stt-requirements.txt
COPY June/services/june-tts/requirements.txt /tmp/tts-requirements.txt

# Install STT dependencies (Whisper)
RUN /venv-stt/bin/pip install "numpy<2.0" && \
    /venv-stt/bin/pip install \
      torch==2.1.2 \
      torchvision==0.16.2 \
      torchaudio==2.1.2 \
      --index-url https://download.pytorch.org/whl/cu121 && \
    /venv-stt/bin/pip install -r /tmp/stt-requirements.txt && \
    rm -rf /root/.cache

# Clone CosyVoice repository with submodules
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice && \
    cd /opt/CosyVoice && \
    git submodule update --init --recursive

# Install TTS dependencies (CosyVoice2) - use conda environment for Python path
RUN /venv-tts/bin/pip install "numpy<2.0" && \
    /venv-tts/bin/pip install \
      torch==2.2.2 \
      torchvision==0.17.2 \
      torchaudio==2.2.2 \
      --index-url https://download.pytorch.org/whl/cu121 && \
    cd /opt/CosyVoice && \
    /venv-tts/bin/pip install -r requirements.txt && \
    /venv-tts/bin/pip install -r /tmp/tts-requirements.txt && \
    rm -rf /root/.cache

# Add CosyVoice and conda environment to Python path
ENV PYTHONPATH="/opt/CosyVoice/third_party/Matcha-TTS:/opt/CosyVoice:/opt/miniconda/envs/cosyvoice/lib/python3.10/site-packages:${PYTHONPATH}"

# Copy application code
COPY June/services/june-stt/ /app/stt/
COPY June/services/june-tts/ /app/tts/

# Environment variables
ENV WHISPER_CACHE_DIR=/app/models \
    MODEL_DIR=/app/pretrained_models \
    COSYVOICE_MODEL=CosyVoice2-0.5B \
    STT_PORT=8001 \
    TTS_PORT=8000

# Create model directories
RUN mkdir -p /app/models /app/pretrained_models /app/cache

# Expose ports
EXPOSE 8000 8001

# Copy startup script
COPY June/services/june-vast/start-both.sh /app/start-both.sh
RUN chmod +x /app/start-both.sh

ENTRYPOINT ["/app/start-both.sh"]