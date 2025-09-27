FROM nvidia/cuda:12.1.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y \
        python3.10 \
        python3.10-venv \
        python3.10-dev \
        build-essential \
        git \
        unzip \
        wget \
        curl \
        libsndfile1 \
        tree \
        pkg-config \
        mecab \
        libmecab-dev \
        mecab-ipadic-utf8 \
    && rm -rf /var/lib/apt/lists/*

# Create Python virtual environment
ENV VENV_DIR="/opt/openvoice/venv"
RUN mkdir -p "$(dirname "$VENV_DIR")" && \
    python3.10 -m venv "$VENV_DIR"

# Activate virtual environment
ENV PATH="$VENV_DIR/bin:$PATH"

# Verify Python and upgrade pip
RUN python -c "import sys; assert sys.version_info[:2]==(3,10)" && \
    python -m pip install --upgrade pip wheel setuptools

# Install PyTorch with CUDA 12.1
RUN pip install "torch>=2.3" --index-url https://download.pytorch.org/whl/cu121

# Install core dependencies
RUN pip install fastapi "uvicorn[standard]" httpx soundfile numpy huggingface_hub

# Install MeCab and fugashi
ENV MECAB_CONFIG=/usr/bin/mecab-config
RUN pip install --no-cache-dir 'fugashi[unidic-lite]==1.3.0' 'unidic-lite<1.1.0'

# Install tokenizers and transformers
ENV PIP_ONLY_BINARY=tokenizers
RUN pip install --upgrade pip wheel setuptools && \
    pip install --no-build-isolation --only-binary=:all: 'tokenizers==0.13.3' && \
    pip install 'transformers==4.27.4'

# Install MeloTTS
RUN pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Download unidic (non-fatal)
RUN python -c "import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'unidic', 'download'])" || true

# Clone and install OpenVoice
ENV OPENVOICE_SRC_DIR="/opt/openvoice/OpenVoice"
RUN git clone https://github.com/myshell-ai/OpenVoice.git "$OPENVOICE_SRC_DIR" && \
    pip install -e "$OPENVOICE_SRC_DIR"

# Create shared directory and copy if it exists
RUN mkdir -p /workspace/shared

# Copy current service files
COPY requirements.txt /workspace/
COPY . /workspace/

# Install additional requirements
RUN pip install --no-cache-dir -r requirements.txt

# Create models directory
ENV OPENVOICE_CHECKPOINTS_V2="/models/openvoice/checkpoints_v2"
RUN mkdir -p "$OPENVOICE_CHECKPOINTS_V2"/{base_speakers,tone_color_converter}

# Download OpenVoice V2 models
RUN python -c "\
import os, shutil; \
from pathlib import Path; \
from huggingface_hub import snapshot_download; \
MODEL_ID = 'myshell-ai/OpenVoiceV2'; \
ROOT = Path('/models/openvoice/checkpoints_v2'); \
BASE = ROOT / 'base_speakers'; \
CONV = ROOT / 'tone_color_converter'; \
BASE.mkdir(parents=True, exist_ok=True); \
CONV.mkdir(parents=True, exist_ok=True); \
patterns = ['base_speakers/*', 'tone_color_converter/*', 'converter/*', 'tone_color_converter_v2/*', 'config.json', '*.pt', '*.pth']; \
print('Downloading models...'); \
snapshot_download(repo_id=MODEL_ID, local_dir=str(ROOT), allow_patterns=patterns); \
print('Models downloaded'); \
"

# Set environment variables
ENV OPENVOICE_DEVICE=cuda
ENV HOST=0.0.0.0
ENV PORT=8000
ENV WORKERS=1
ENV PYTHONPATH="/workspace:/workspace/shared"
ENV CORS_ALLOW_ORIGINS="*"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
