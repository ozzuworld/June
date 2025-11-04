# June vast.ai combined STT+TTS image with CosyVoice 2 for ultra-low latency
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

# Prevent interactive prompts during build
ARG DEBIAN_FRONTEND=noninteractive
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=/usr/local/cuda/bin:$PATH

# Base system deps (both services + CosyVoice requirements)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip \
    ffmpeg espeak-ng libsndfile1 libportaudio2 \
    ca-certificates curl git wget \
    build-essential cmake sox libsox-dev git-lfs unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda and configure conda-forge only (avoid defaults/ToS)
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/miniconda && \
    rm /tmp/miniconda.sh
ENV PATH="/opt/miniconda/bin:$PATH"
RUN conda config --system --remove-key channels || true && \
    conda config --system --add channels conda-forge && \
    conda config --system --set channel_priority strict && \
    conda clean -afy

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

# TTS deps: CosyVoice 2 for streaming ultra-low latency synthesis
RUN /venv-tts/bin/pip install "numpy<2.0" && \
    /venv-tts/bin/pip install torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 \
      --index-url https://download.pytorch.org/whl/cu121 && \
    # Install pynini via pip wheel that supports many Python versions (avoids conda solver pins)
    /venv-tts/bin/pip install pynini==2.1.6.post1 && \
    # Install CosyVoice 2 dependencies
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
    # Clone CosyVoice (source usage; not a pip package)
    git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice && \
    cd /opt/CosyVoice && git submodule update --init --recursive && \
    # Install CosyVoice repo requirements
    /venv-tts/bin/pip install -r requirements.txt && \
    # Optional: ensure WeTextProcessing present
    /venv-tts/bin/pip install WeTextProcessing==1.0.3 && \
    true

# Bake pretrained models into the image (ModelScope snapshot_download)
ENV COSYVOICE_MODELS=/app/models/cosyvoice \
    TTS_HOME=/app/models \
    TTS_CACHE_PATH=/app/cache
RUN mkdir -p /app/models/pretrained_models /app/cache && \
    /venv-tts/bin/python - << 'PY'
from modelscope import snapshot_download
import os
pairs = [
    ('iic/CosyVoice2-0.5B', 'CosyVoice2-0.5B'),
]
os.makedirs('/app/models/pretrained_models', exist_ok=True)
for repo, name in pairs:
    local_dir = f'/app/models/pretrained_models/{name}'
    if not os.path.exists(local_dir):
        snapshot_download(repo, local_dir=local_dir)
PY

# Add CosyVoice source to PYTHONPATH for runtime imports
ENV PYTHONPATH=/app:/opt/CosyVoice/third_party/Matcha-TTS:/opt/CosyVoice:$PYTHONPATH

# Copy application code
COPY June/services/june-stt/ /app/stt/
COPY June/services/june-tts/ /app/tts/

# Runtime env with model paths
ENV WHISPER_CACHE_DIR=/app/models \
    COQUI_TTS_AGREED=1 \
    STT_PORT=8001 \
    TTS_PORT=8000

# Create model directories
RUN mkdir -p /app/models/cosyvoice /app/voices /app/cache

# Expose service ports
EXPOSE 8000 8001

# Add entrypoint script that downloads models and starts both services
COPY June/services/june-vast/start-both.sh /app/start-both.sh
RUN chmod +x /app/start-both.sh

ENTRYPOINT ["/app/start-both.sh"]