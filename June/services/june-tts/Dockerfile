FROM nvidia/cuda:12.1.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /workspace

# ============================================================================
# SYSTEM DEPENDENCIES
# ============================================================================

# Install system packages including ffmpeg and audio libraries
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
        ffmpeg \
        libavcodec-extra \
        sox \
        libsox-fmt-all \
    && rm -rf /var/lib/apt/lists/*

# ============================================================================
# PYTHON ENVIRONMENT SETUP
# ============================================================================

# Create Python virtual environment
ENV VENV_DIR="/opt/openvoice/venv"
RUN mkdir -p "$(dirname "$VENV_DIR")" && \
    python3.10 -m venv "$VENV_DIR"

# Activate virtual environment for all subsequent commands
ENV PATH="$VENV_DIR/bin:$PATH"

# Verify Python version and upgrade pip
RUN python -c "import sys; assert sys.version_info[:2]==(3,10), f'Expected Python 3.10, got {sys.version}'" && \
    python -m pip install --upgrade pip wheel setuptools

# ============================================================================
# PYTORCH INSTALLATION
# ============================================================================

# Install PyTorch with CUDA 12.1 support
RUN pip install "torch>=2.3" "torchaudio>=2.3" --index-url https://download.pytorch.org/whl/cu121

# ============================================================================
# CORE DEPENDENCIES
# ============================================================================

# Install core ML and audio processing libraries
RUN pip install \
    fastapi==0.104.1 \
    "uvicorn[standard]==0.24.0" \
    httpx==0.25.2 \
    soundfile==0.12.1 \
    numpy>=1.24.0 \
    huggingface_hub \
    librosa==0.10.1 \
    pydub \
    scipy>=1.11.0

# ============================================================================
# MECAB AND FUGASHI FOR JAPANESE TEXT PROCESSING
# ============================================================================

# Install MeCab dependencies for Japanese text processing
ENV MECAB_CONFIG=/usr/bin/mecab-config
RUN pip install --no-cache-dir 'fugashi[unidic-lite]==1.3.0' 'unidic-lite<1.1.0'

# Verify MeCab installation
RUN mecab -v && python -c "import fugashi; print('✅ MeCab and fugashi working')"

# ============================================================================
# TOKENIZERS AND TRANSFORMERS (PREBUILT WHEELS)
# ============================================================================

# Force binary wheels to avoid Rust compilation
ENV PIP_ONLY_BINARY=tokenizers
RUN pip install --no-build-isolation --only-binary=:all: 'tokenizers==0.13.3' && \
    pip install 'transformers==4.27.4'

# ============================================================================
# MELO TTS INSTALLATION
# ============================================================================

# Install MeloTTS from GitHub
RUN pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Download unidic dictionary (optional, non-fatal)
RUN python -c "import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'unidic', 'download'])" || \
    echo "⚠️ unidic download failed (non-fatal)"

# ============================================================================
# OPENVOICE INSTALLATION
# ============================================================================

# Clone and install OpenVoice
ENV OPENVOICE_SRC_DIR="/opt/openvoice/OpenVoice"
RUN git clone https://github.com/myshell-ai/OpenVoice.git "$OPENVOICE_SRC_DIR" && \
    pip install -e "$OPENVOICE_SRC_DIR"

# ============================================================================
# CREATE MODEL DIRECTORIES
# ============================================================================

# Create models directory with proper structure
ENV OPENVOICE_CHECKPOINTS_V2="/models/openvoice/checkpoints_v2"
RUN mkdir -p "$OPENVOICE_CHECKPOINTS_V2"/{base_speakers,tone_color_converter}

# Copy model setup script
COPY model_setup.py /workspace/

# Run model setup script
RUN python /workspace/model_setup.py

# Verify final structure and file sizes
RUN echo "📁 Final model structure:" && \
    find /models/openvoice/checkpoints_v2 -type f -name "*.pth" -o -name "*.pt" -o -name "config.json" | \
    xargs ls -lh && \
    echo "✅ Model files verified"

# ============================================================================
# APPLICATION SETUP
# ============================================================================

# Create shared directory structure (fix for import errors)
RUN mkdir -p /workspace/shared

# Create minimal shared module first
RUN echo "# Minimal shared module" > /workspace/shared/__init__.py && \
    echo "def require_service_auth(): return lambda: {'client_id': 'docker'}" > /workspace/shared/auth.py

# Copy shared module if it exists (FIXED: added trailing slash)
COPY shared/ /workspace/shared/

# Install shared module
RUN pip install -e /workspace/shared

# Copy requirements and install additional dependencies
COPY requirements.txt /workspace/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ /workspace/app/

# Copy any Python files in root (FIXED: added trailing slash for multiple files)  
COPY *.py /workspace/

# ============================================================================
# ENVIRONMENT CONFIGURATION
# ============================================================================

# Set environment variables
ENV OPENVOICE_DEVICE=cuda
ENV HOST=0.0.0.0
ENV PORT=8000
ENV WORKERS=1
ENV PYTHONPATH="/workspace:/workspace/shared"
ENV CORS_ALLOW_ORIGINS="*"
ENV OPENVOICE_CHECKPOINTS_V2="/models/openvoice/checkpoints_v2"

# Audio processing environment
ENV MELO_LANGUAGE=EN
ENV MELO_SPEAKER_ID=0
ENV MAX_FILE_SIZE=20971520
ENV MAX_TEXT_LEN=2000

# ============================================================================
# FINAL SETUP
# ============================================================================

# Create non-root user for security (optional)
RUN groupadd -r appuser && \
    useradd -r -g appuser appuser && \
    chown -R appuser:appuser /workspace /models

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Expose port
EXPOSE 8000

# Switch to non-root user
USER appuser

# Start command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]