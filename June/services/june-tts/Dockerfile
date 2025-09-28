# Simple June TTS Dockerfile - Based on proven install script
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MODEL_ID=myshell-ai/OpenVoiceV2
ENV OPENVOICE_CHECKPOINTS_V2=/models/openvoice/checkpoints_v2
ENV VENV_DIR=/opt/openvoice/venv
ENV OPENVOICE_SRC_DIR=/opt/openvoice/OpenVoice
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies (like your script, but Python 3.10 is already available)
RUN apt-get update && apt-get install -y \
    build-essential git unzip wget curl libsndfile1 tree pkg-config \
    mecab libmecab-dev mecab-ipadic-utf8 mecab-utils \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment (using the existing python3.10)
RUN python3.10 -m venv $VENV_DIR

# Verify Python version (like your script)
RUN $VENV_DIR/bin/python -c "import sys; assert sys.version_info[:2]==(3,10), f'Expected Python 3.10, got: {sys.version}'; print('Python OK:', sys.version)"

# Upgrade pip (like your script)
RUN $VENV_DIR/bin/python -m pip install --upgrade pip wheel setuptools

# Install PyTorch - Your script's GPU detection logic adapted for Docker
# Since we're building without GPU but deploying to GPU, install CUDA version
RUN echo "🧠 Installing PyTorch with CUDA support for deployment" && \
    $VENV_DIR/bin/pip install "torch>=2.3" --index-url https://download.pytorch.org/whl/cu121

# Install core dependencies (like your script)
RUN $VENV_DIR/bin/pip install fastapi "uvicorn[standard]" httpx soundfile numpy huggingface_hub

# Install MeCab + fugashi (exactly like your script)
ENV MECAB_CONFIG=/usr/bin/mecab-config
RUN mecab -v && \
    $VENV_DIR/bin/pip install --no-cache-dir 'fugashi[unidic-lite]==1.3.0' 'unidic-lite<1.1.0'

# Test fugashi (like your script)
RUN $VENV_DIR/bin/python -c "import fugashi; print('fugashi OK:', getattr(fugashi, '__version__', 'n/a'))"

# Install tokenizers with exact settings from your script
RUN $VENV_DIR/bin/pip install --upgrade pip wheel setuptools
ENV PIP_ONLY_BINARY=tokenizers
RUN $VENV_DIR/bin/pip install --no-build-isolation --only-binary=:all: 'tokenizers==0.13.3'
RUN $VENV_DIR/bin/pip install 'transformers==4.27.4'

# Install MeloTTS (like your script)
RUN $VENV_DIR/bin/pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Try unidic download (exactly like your script)
RUN $VENV_DIR/bin/python -c "import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'unidic', 'download'])" || true

# Clone and install OpenVoice (like your script)
RUN rm -rf $OPENVOICE_SRC_DIR && \
    git clone https://github.com/myshell-ai/OpenVoice.git $OPENVOICE_SRC_DIR && \
    $VENV_DIR/bin/pip install -e $OPENVOICE_SRC_DIR

# Create model directories (like your script)
RUN mkdir -p $OPENVOICE_CHECKPOINTS_V2/base_speakers && \
    mkdir -p $OPENVOICE_CHECKPOINTS_V2/tone_color_converter

# Set working directory
WORKDIR /workspace

# Copy shared module and install
COPY shared/ /workspace/shared/
RUN $VENV_DIR/bin/pip install -e /workspace/shared/

# Install additional TTS requirements
COPY requirements.txt /workspace/
RUN $VENV_DIR/bin/pip install --no-cache-dir -r requirements.txt

# Copy and run model setup (uses your proven model_setup.py)
COPY model_setup.py /workspace/
RUN $VENV_DIR/bin/python /workspace/model_setup.py

# Copy application files
COPY app/ /workspace/app/

# Set runtime environment
ENV PYTHONPATH="/workspace:/workspace/shared"
ENV PATH="$VENV_DIR/bin:$PATH"
ENV HOST=0.0.0.0
ENV PORT=8000
ENV MELO_LANGUAGE=EN
ENV MELO_SPEAKER_ID=0
ENV CORS_ALLOW_ORIGINS="*"

# Verification (test imports work - will use CPU during build, GPU at runtime)
RUN echo "🔍 Build-time verification (CPU):" && \
    $VENV_DIR/bin/python -c "import torch; print('PyTorch version:', torch.__version__, 'CUDA available:', torch.cuda.is_available())" && \
    $VENV_DIR/bin/python -c "from melo.api import TTS; print('✅ MeloTTS imports OK')" && \
    $VENV_DIR/bin/python -c "import fugashi; print('✅ Fugashi OK')" && \
    $VENV_DIR/bin/python -c "from fastapi import FastAPI; print('✅ FastAPI OK')" && \
    echo "🎉 Build verification complete!"

# Create non
