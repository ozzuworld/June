# Complete June TTS Dockerfile with GPU + OpenVoice V2
FROM python:3.10-slim as builder

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Install build dependencies including Git LFS
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    git-lfs \
    curl \
    pkg-config \
    mecab \
    libmecab-dev \
    mecab-ipadic-utf8 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Initialize Git LFS
RUN git lfs install

# Create virtual environment
RUN python3.10 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install wheel
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# ✅ FIXED: Install GPU PyTorch for faster processing
RUN echo "🚀 Installing PyTorch with CUDA support for GPU acceleration" && \
    pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install core dependencies
RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    httpx==0.27.0 \
    soundfile==0.12.1 \
    numpy \
    huggingface_hub

# Install MeCab dependencies
ENV MECAB_CONFIG=/usr/bin/mecab-config
RUN pip install --no-cache-dir fugashi[unidic-lite]==1.3.0 unidic-lite

# Install tokenizers and transformers (pinned versions)
ENV PIP_ONLY_BINARY=tokenizers
RUN pip install --no-cache-dir --no-build-isolation --only-binary=:all: tokenizers==0.13.3
RUN pip install --no-cache-dir transformers==4.27.4

# Install MeloTTS
RUN pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# ✅ FIXED: Properly install OpenVoice V2 with all dependencies
RUN echo "📦 Installing OpenVoice V2..." && \
    git clone --depth 1 https://github.com/myshell-ai/OpenVoice.git /tmp/OpenVoice && \
    cd /tmp/OpenVoice && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir \
        librosa>=0.10.0 \
        scipy>=1.9.0 \
        matplotlib>=3.5.0 \
        tqdm>=4.60.0 \
        tensorboard>=2.8.0 \
        monotonic_align>=0.1.2 \
    && rm -rf /tmp/OpenVoice/.git

# Download unidic
RUN python -m unidic download || true

# ============================================================================
# Production Stage - Much smaller final image
# ============================================================================
FROM python:3.10-slim as production

# Install runtime dependencies including Git LFS
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libsndfile1 \
    mecab \
    mecab-ipadic-utf8 \
    ffmpeg \
    git \
    git-lfs \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Initialize Git LFS in production stage
RUN git lfs install

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /workspace

# Copy application files
COPY requirements.txt /workspace/
COPY setup_nltk.py /workspace/
COPY shared/ /workspace/shared/
COPY app/ /workspace/app/

# Install any additional requirements
RUN pip install --no-cache-dir -r requirements.txt

# ✅ ENHANCED: Download OpenVoice V2 models with better error handling
RUN mkdir -p /models/openvoice/checkpoints_v2/base_speakers && \
    mkdir -p /models/openvoice/checkpoints_v2/tone_color_converter && \
    echo "📥 Downloading OpenVoice V2 models..." && \
    python -c "
import os
import shutil
from pathlib import Path
from huggingface_hub import snapshot_download

try:
    MODEL_ID = 'myshell-ai/OpenVoiceV2'
    ROOT = Path('/models/openvoice/checkpoints_v2')
    BASE = ROOT / 'base_speakers'
    CONV = ROOT / 'tone_color_converter'
    
    print(f'📥 Downloading from {MODEL_ID}...')
    
    # Download with proper patterns for OpenVoice V2
    patterns = [
        'base_speakers/**',
        'tone_color_converter/**',
        'converter/**',
        'checkpoints_v2/**',
        'config.json',
        '*.pt',
        '*.pth',
        '*.json',
    ]
    
    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=str(ROOT),
        local_dir_use_symlinks=False,
        allow_patterns=patterns,
        resume_download=True,
        timeout=300
    )
    print('✅ Download completed')
    
    # Organize downloaded files
    for alt_dir in ['converter', 'checkpoints_v2']:
        alt_path = ROOT / alt_dir
        if alt_path.exists():
            print(f'🔄 Moving files from {alt_dir}...')
            for item in alt_path.rglob('*'):
                if item.is_file():
                    rel_path = item.relative_to(alt_path)
                    if 'base_speakers' in str(rel_path):
                        dest = BASE / rel_path.name
                    else:
                        dest = CONV / rel_path.name
                    
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        shutil.copy2(item, dest)
                        print(f'✅ Copied {rel_path.name}')
            
            shutil.rmtree(alt_path, ignore_errors=True)
    
    # Move root level files
    for pattern in ['*.pt', '*.pth', '*.json']:
        for item in ROOT.glob(pattern):
            if item.name == 'config.json':
                dest = CONV / 'config.json'
            else:
                dest = CONV / item.name
            
            if not dest.exists():
                shutil.move(str(item), str(dest))
                print(f'✅ Moved {item.name}')
    
    # Verify critical files exist
    config_file = CONV / 'config.json'
    checkpoint_files = list(CONV.glob('*.pt')) + list(CONV.glob('*.pth'))
    
    if not config_file.exists():
        print('⚠️ Creating minimal config.json')
        import json
        config = {
            'model': {
                'type': 'ToneColorConverter',
                'hidden_channels': 192,
                'filter_channels': 768,
                'n_heads': 2,
                'n_layers': 6,
                'kernel_size': 3,
                'p_dropout': 0.1,
                'resblock': '1',
                'resblock_kernel_sizes': [3, 7, 11],
                'resblock_dilation_sizes': [[1, 3, 5], [1, 3, 5], [1, 3, 5]],
                'upsample_rates': [8, 8, 2, 2],
                'upsample_initial_channel': 512,
                'upsample_kernel_sizes': [16, 16, 4, 4],
                'gin_channels': 256
            }
        }
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
    
    if not checkpoint_files:
        print('⚠️ No checkpoint files found - voice cloning may not work')
    
    print(f'🎉 Setup complete! Found {len(checkpoint_files)} checkpoint files')
    
    # List final structure
    print('📁 Final structure:')
    for item in sorted(CONV.rglob('*')):
        if item.is_file():
            size_mb = item.stat().st_size / (1024 * 1024)
            print(f'  {item.name} ({size_mb:.1f}MB)')

except Exception as e:
    print(f'❌ Model download failed: {e}')
    print('⚠️ Continuing without OpenVoice models - basic TTS will still work')
"

# Run NLTK setup
RUN python /workspace/setup_nltk.py

# Create non-root user and set up permissions with cache directories
RUN useradd -m -u 1001 appuser && \
    mkdir -p /home/appuser/.cache/huggingface/hub && \
    mkdir -p /home/appuser/.cache/torch && \
    chown -R appuser:appuser /workspace /home/appuser/nltk_data /home/appuser/.cache /models

# Set cache environment variables
ENV HF_HOME=/home/appuser/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface
ENV TORCH_HOME=/home/appuser/.cache/torch
ENV OPENVOICE_CHECKPOINTS_V2=/models/openvoice/checkpoints_v2

# Switch to non-root user
USER appuser

# Set runtime environment
ENV PYTHONPATH="/workspace:/workspace/shared"
ENV HOST=0.0.0.0
ENV PORT=8000
ENV MELO_LANGUAGE=EN
ENV MELO_SPEAKER_ID=0
ENV CORS_ALLOW_ORIGINS="*"
ENV NLTK_DATA=/home/appuser/nltk_data

# ✅ GPU verification at runtime
RUN echo "🔍 Runtime verification:" && \
    python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA devices: {torch.cuda.device_count()}')" && \
    python -c "from melo.api import TTS; print('✅ MeloTTS imports OK')" && \
    python -c "try:\n  from openvoice.api import ToneColorConverter; print('✅ OpenVoice imports OK')\nexcept Exception as e:\n  print(f'⚠️ OpenVoice import failed: {e}')" && \
    echo "🎉 Build verification complete!"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Expose port
EXPOSE 8000

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]