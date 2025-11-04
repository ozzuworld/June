# June TTS service with CosyVoice 2.0 for ultra-low latency synthesis
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

# Prevent interactive prompts during build
ARG DEBIAN_FRONTEND=noninteractive
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=/usr/local/cuda/bin:$PATH

# Install system dependencies including miniconda for pynini
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip \
    ffmpeg espeak-ng libsndfile1 libportaudio2 \
    ca-certificates curl git wget build-essential \
    sox libsox-dev git-lfs unzip \
    && rm -rf /var/lib/apt/lists/*

# Install miniconda for conda-forge pynini installation
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/miniconda && \
    rm /tmp/miniconda.sh
ENV PATH="/opt/miniconda/bin:$PATH"

WORKDIR /app

# Create TTS virtual environment
RUN python3.10 -m venv /venv-tts
ENV PATH="/venv-tts/bin:$PATH"

# Copy shared module and requirements
COPY June/services/shared/ /app/shared/
COPY June/services/june-tts/requirements.txt /tmp/tts-requirements.txt

# Install shared module
RUN /venv-tts/bin/pip install --upgrade pip setuptools wheel && \
    /venv-tts/bin/pip install -e /app/shared

# Install TTS dependencies with CosyVoice 2 support
RUN /venv-tts/bin/pip install "numpy<2.0" && \
    /venv-tts/bin/pip install torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 \
      --index-url https://download.pytorch.org/whl/cu121 && \
    # Install pynini from conda-forge to avoid authentication issues
    conda install -y -c conda-forge pynini=2.1.5 && \
    # Install CosyVoice dependencies
    /venv-tts/bin/pip install \
      modelscope==1.9.5 \
      onnxruntime-gpu==1.16.0 \
      librosa==0.10.1 \
      scipy==1.11.0 \
      soundfile==0.12.1 \
      accelerate==0.24.1 \
      transformers==4.35.0 \
      onnx==1.16.0 \
      protobuf==3.20.3 && \
    # Clone and install CosyVoice with proper submodule initialization
    git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /tmp/cosyvoice && \
    cd /tmp/cosyvoice && \
    git submodule update --init --recursive && \
    /venv-tts/bin/pip install --no-deps -e . && \
    # Install remaining TTS service dependencies
    /venv-tts/bin/pip install -r /tmp/tts-requirements.txt && \
    # Clean up
    rm -rf /root/.cache /tmp/cosyvoice

# Copy application code
COPY June/services/june-tts/ /app/tts/

# Set runtime environment
ENV TTS_CACHE_PATH=/app/cache
ENV TTS_HOME=/app/models
ENV COQUI_TOS_AGREED=1
ENV TTS_PORT=8000
ENV PYTHONPATH=/app
ENV COSYVOICE_MODEL_DIR=/app/models/cosyvoice

# Create necessary directories
RUN mkdir -p /app/cache /app/models/cosyvoice

# Expose TTS service port
EXPOSE 8000

# Default command to run TTS service
CMD ["/venv-tts/bin/python", "/app/tts/main.py"]