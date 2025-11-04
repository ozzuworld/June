# CosyVoice2 TTS Service - Official Implementation
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

# Environment setup
ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=/usr/local/cuda/bin:$PATH

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip \
    ffmpeg sox libsox-dev \
    ca-certificates curl wget git git-lfs \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda for pynini (required by CosyVoice)
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/miniconda && \
    rm /tmp/miniconda.sh
ENV PATH="/opt/miniconda/bin:$PATH"

WORKDIR /app

# Create Python virtual environment
RUN python3.10 -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install pynini via conda (required by WeTextProcessing)
RUN conda install -y -c conda-forge pynini==2.1.5

# Copy requirements and install dependencies
COPY June/services/june-tts/requirements.txt /tmp/requirements.txt
RUN /venv/bin/pip install --upgrade pip setuptools wheel && \
    /venv/bin/pip install -r /tmp/requirements.txt

# Clone CosyVoice repository with submodules
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice && \
    cd /opt/CosyVoice && \
    git submodule update --init --recursive && \
    /venv/bin/pip install --no-deps -e . && \
    rm -rf /root/.cache

# Add Matcha-TTS to Python path (required by CosyVoice)
ENV PYTHONPATH="/opt/CosyVoice/third_party/Matcha-TTS:$PYTHONPATH"

# Copy shared module if exists
COPY June/services/shared/ /app/shared/ 2>/dev/null || true
RUN if [ -d /app/shared ]; then /venv/bin/pip install -e /app/shared; fi

# Copy application code
COPY June/services/june-tts/ /app/

# Create model directory
RUN mkdir -p /app/pretrained_models

# Environment variables
ENV MODEL_DIR=/app/pretrained_models
ENV COSYVOICE_MODEL=CosyVoice2-0.5B

EXPOSE 8000

CMD ["/venv/bin/python", "/app/main.py"]