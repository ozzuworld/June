# June vast.ai combined STT+TTS image with CosyVoice2 (CUDA 12.4 aligned)
FROM nvidia/cuda:12.4.1-cudnn9-devel-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=/usr/local/cuda/bin:$PATH
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip python3.10-dev \
    ffmpeg sox libsox-dev libsndfile1 libsndfile1-dev \
    ca-certificates curl wget git git-lfs \
    build-essential cmake pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/miniconda && rm /tmp/miniconda.sh
ENV PATH="/opt/miniconda/bin:$PATH"
RUN conda config --system --remove-key channels || true && \
    conda config --system --add channels conda-forge && \
    conda config --system --set channel_priority strict

WORKDIR /app

# CosyVoice conda env
RUN conda create -n cosyvoice python=3.10 -y && \
    conda run -n cosyvoice conda install -y -c conda-forge pynini==2.1.5 && \
    conda clean -afy

# Create single shared venv for both services (to ensure torch compatibility)
RUN python3.10 -m venv /venv

# Install PyTorch stack FIRST for both services (CUDA 12.4 + cuDNN 9)
RUN /venv/bin/pip install --upgrade pip setuptools wheel && \
    /venv/bin/pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cu124 \
      torch==2.6.0+cu124 \
      torchvision==0.21.0+cu124 \
      torchaudio==2.6.0+cu124

# Shared module
COPY June/services/shared/ /app/shared/
RUN if [ -d /app/shared ]; then \
      /venv/bin/pip install -e /app/shared ; \
    fi

# Copy requirements
COPY June/services/june-stt/requirements.txt /tmp/stt-requirements.txt
COPY June/services/june-tts/requirements.txt /tmp/tts-requirements.txt

# Install STT dependencies (without torch - already installed)
RUN /venv/bin/pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn==0.24.0 \
    livekit==0.11.1 \
    transformers>=4.30.0 \
    soundfile==0.12.1 \
    scipy>=1.13.0 \
    librosa>=0.10.0 \
    numpy>=2.0.0,<2.1.0 \
    pyannote.audio>=3.3.0 \
    faster-whisper>=1.1.1 \
    httpx==0.25.2 \
    python_multipart && \
    rm -rf /root/.cache

# Install WhisperX (it will use existing torch installation)
RUN /venv/bin/pip install --no-cache-dir \
    git+https://github.com/m-bain/whisperX.git && \
    rm -rf /root/.cache

# CosyVoice checkout
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice && \
    cd /opt/CosyVoice && git submodule update --init --recursive

# Install CosyVoice + TTS dependencies (torch already installed)
RUN cd /opt/CosyVoice && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt && \
    /venv/bin/pip install --no-cache-dir -r /tmp/tts-requirements.txt && \
    rm -rf /root/.cache

# PYTHONPATH for CosyVoice + conda
ENV PYTHONPATH="/opt/CosyVoice/third_party/Matcha-TTS:/opt/CosyVoice:/opt/miniconda/envs/cosyvoice/lib/python3.10/site-packages"

# Copy app code
COPY June/services/june-stt/ /app/stt/
COPY June/services/june-tts/ /app/tts/

# Runtime env
ENV WHISPER_CACHE_DIR=/app/models \
    MODEL_DIR=/app/pretrained_models \
    COSYVOICE_MODEL=CosyVoice2-0.5B \
    STT_PORT=8001 \
    TTS_PORT=8000

RUN mkdir -p /app/models /app/pretrained_models /app/cache

EXPOSE 8000 8001

COPY June/services/june-vast/start-both.sh /app/start-both.sh
RUN chmod +x /app/start-both.sh

ENTRYPOINT ["/app/start-both.sh"]