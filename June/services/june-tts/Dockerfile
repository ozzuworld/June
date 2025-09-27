# ============================================================================
# BUILD STAGE - All the heavy compilation and downloads
# ============================================================================
FROM nvidia/cuda:12.1.1-devel-ubuntu22.04 as builder

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
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
        pkg-config \
        mecab \
        libmecab-dev \
        mecab-ipadic-utf8 \
        ffmpeg \
        libavcodec-extra \
        sox \
        libsox-fmt-all \
    && rm -rf /var/lib/apt/lists/*

# Create Python virtual environment
ENV VENV_DIR="/opt/openvoice/venv"
RUN mkdir -p "$(dirname "$VENV_DIR")" && \
    python3.10 -m venv "$VENV_DIR"

ENV PATH="$VENV_DIR/bin:$PATH"

# Upgrade pip
RUN python -c "import sys; assert sys.version_info[:2]==(3,10), f'Expected Python 3.10, got {sys.version}'" && \
    python -m pip install --upgrade pip wheel setuptools

# Install PyTorch with CUDA 12.1 support
RUN pip install "torch>=2.3" "torchaudio>=2.3" --index-url https://download.pytorch.org/whl/cu121

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

# Install MeCab dependencies
ENV MECAB_CONFIG=/usr/bin/mecab-config
RUN pip install --no-cache-dir 'fugashi[unidic-lite]==1.3.0' 'unidic-lite<1.1.0'

# Install tokenizers and transformers
ENV PIP_ONLY_BINARY=tokenizers
RUN pip install --no-build-isolation --only-binary=:all: 'tokenizers==0.13.3' && \
    pip install 'transformers==4.27.4'

# Install MeloTTS
RUN pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Download unidic dictionary
RUN python -c "import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'unidic', 'download'])" || \
    echo "⚠️ unidic download failed (non-fatal)"

# Clone and install OpenVoice
ENV OPENVOICE_SRC_DIR="/opt/openvoice/OpenVoice"
RUN git clone https://github.com/myshell-ai/OpenVoice.git "$OPENVOICE_SRC_DIR" && \
    pip install -e "$OPENVOICE_SRC_DIR"

# Create models directory and setup
ENV OPENVOICE_CHECKPOINTS_V2="/models/openvoice/checkpoints_v2"
RUN mkdir -p "$OPENVOICE_CHECKPOINTS_V2"/{base_speakers,tone_color_converter}

# Copy and run model setup (if you have it)
COPY model_setup.py /tmp/
RUN python /tmp/model_setup.py || echo "model_setup.py not found or failed"

# ============================================================================
# RUNTIME STAGE - Minimal runtime environment
# ============================================================================
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install ONLY runtime dependencies (no build tools)
RUN apt-get update && \
    apt-get install -y \
        python3.10 \
        curl \
        libsndfile1 \
        mecab \
        mecab-ipadic-utf8 \
        ffmpeg \
        sox \
        libsox-fmt-all \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire virtual environment from builder
COPY --from=builder /opt/openvoice/venv /opt/openvoice/venv

# Copy models directory
COPY --from=builder /models /models

# Copy OpenVoice source (needed for runtime)
COPY --from=builder /opt/openvoice/OpenVoice /opt/openvoice/OpenVoice

# Set working directory
WORKDIR /workspace

# Activate virtual environment
ENV PATH="/opt/openvoice/venv/bin:$PATH"

# Create shared directory structure
RUN mkdir -p /workspace/shared

# Create minimal shared module
RUN echo "# Minimal shared module" > /workspace/shared/__init__.py && \
    echo "def require_service_auth(): return lambda: {'client_id': 'docker'}" > /workspace/shared/auth.py

# Copy application files
COPY shared/ /workspace/shared/
COPY requirements.txt /workspace/
COPY app/ /workspace/app/
COPY *.py /workspace/

# Install additional requirements (should be fast since big packages already installed)
RUN pip install --no-cache-dir -r requirements.txt

# Install shared module
RUN pip install -e /workspace/shared

# Environment variables
ENV OPENVOICE_DEVICE=cuda
ENV HOST=0.0.0.0
ENV PORT=8000
ENV WORKERS=1
ENV PYTHONPATH="/workspace:/workspace/shared"
ENV CORS_ALLOW_ORIGINS="*"
ENV OPENVOICE_CHECKPOINTS_V2="/models/openvoice/checkpoints_v2"
ENV MECAB_CONFIG=/usr/bin/mecab-config

# Audio processing environment
ENV MELO_LANGUAGE=EN
ENV MELO_SPEAKER_ID=0
ENV MAX_FILE_SIZE=20971520
ENV MAX_TEXT_LEN=2000

# Create non-root user
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
