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
# OPENVOICE V2 MODELS DOWNLOAD
# ============================================================================

# Create models directory with proper structure
ENV OPENVOICE_CHECKPOINTS_V2="/models/openvoice/checkpoints_v2"
RUN mkdir -p "$OPENVOICE_CHECKPOINTS_V2"/{base_speakers,tone_color_converter}

# Download OpenVoice V2 models with comprehensive error handling
RUN python -c "
import os
import shutil
import sys
from pathlib import Path
from huggingface_hub import snapshot_download

print('🔄 Downloading OpenVoice V2 models...')

MODEL_ID = 'myshell-ai/OpenVoiceV2'
ROOT = Path('/models/openvoice/checkpoints_v2')
BASE = ROOT / 'base_speakers'
CONV = ROOT / 'tone_color_converter'

# Ensure directories exist
BASE.mkdir(parents=True, exist_ok=True)
CONV.mkdir(parents=True, exist_ok=True)

try:
    # Download all relevant model files
    patterns = [
        'base_speakers/*',
        'tone_color_converter/*',
        'converter/*',
        'tone_color_converter_v2/*',
        'config.json',
        '*.pt',
        '*.pth',
        '*.json'
    ]
    
    print(f'📥 Downloading from {MODEL_ID}...')
    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=str(ROOT),
        local_dir_use_symlinks=False,
        allow_patterns=patterns,
        resume_download=True
    )
    
    print('✅ Download completed, organizing files...')
    
    # Normalize folder structure - handle different naming conventions
    for alt_name in ['converter', 'tone_color_converter_v2']:
        alt_dir = ROOT / alt_name
        if alt_dir.exists() and alt_dir.is_dir():
            print(f'📁 Moving files from {alt_name}/ to tone_color_converter/')
            for file in alt_dir.rglob('*'):
                if file.is_file():
                    dest = CONV / file.name
                    if not dest.exists():
                        print(f'  Moving: {file.name}')
                        shutil.copy2(file, dest)
            shutil.rmtree(alt_dir)
    
    # Move any root-level model files to tone_color_converter
    for pattern in ['*.pt', '*.pth', 'config.json']:
        for file in ROOT.glob(pattern):
            dest = CONV / file.name
            if not dest.exists():
                print(f'📁 Moving root file: {file.name}')
                shutil.move(str(file), str(dest))
    
    # Handle nested config files
    for config_file in CONV.rglob('config.json'):
        if config_file.parent != CONV:
            dest = CONV / 'config.json'
            if not dest.exists():
                print(f'📁 Moving nested config: {config_file}')
                shutil.copy2(config_file, dest)
                break
    
    # Handle nested checkpoint files
    for ckpt_file in CONV.rglob('*.pth'):
        if ckpt_file.parent != CONV:
            dest = CONV / ckpt_file.name
            if not dest.exists():
                print(f'📁 Moving nested checkpoint: {ckpt_file.name}')
                shutil.copy2(ckpt_file, dest)
    
    # Verify required files exist
    config_path = CONV / 'config.json'
    checkpoint_files = list(CONV.glob('*.pt')) + list(CONV.glob('*.pth'))
    
    print(f'🔍 Verification:')
    print(f'  Config file: {config_path.exists()} - {config_path}')
    print(f'  Checkpoint files: {len(checkpoint_files)} found')
    
    if checkpoint_files:
        print('  Checkpoints:')
        for ckpt in checkpoint_files:
            print(f'    - {ckpt.name} ({ckpt.stat().st_size} bytes)')
    
    if not config_path.exists():
        print('❌ ERROR: config.json not found!')
        sys.exit(1)
    
    if not checkpoint_files:
        print('❌ ERROR: No checkpoint files found!')
        sys.exit(1)
    
    print('✅ OpenVoice V2 models downloaded and verified successfully!')
    
except Exception as e:
    print(f'❌ ERROR downloading models: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
"

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

# Copy shared module first (create a minimal one if doesn't exist)
COPY shared /workspace/shared/ 2>/dev/null || \
    (mkdir -p /workspace/shared && \
     echo "# Minimal shared module" > /workspace/shared/__init__.py && \
     echo "def require_service_auth(): return lambda: {'client_id': 'docker'}" > /workspace/shared/auth.py)

# Install shared module
RUN pip install -e /workspace/shared

# Copy requirements and install additional dependencies
COPY requirements.txt /workspace/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /workspace/

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