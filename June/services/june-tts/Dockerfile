# Fixed OpenVoice V2 Dockerfile - Solution 2: PatchELF Fix
# This approach fixes the ctranslate2 executable stack issue using patchelf
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Install ALL dependencies including patchelf for fixing ctranslate2
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Runtime dependencies
    curl \
    libsndfile1 \
    mecab \
    mecab-ipadic-utf8 \
    ffmpeg \
    git \
    git-lfs \
    # Build dependencies
    build-essential \
    pkg-config \
    libmecab-dev \
    # CRITICAL: patchelf for fixing executable stack
    patchelf \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Initialize Git LFS
RUN git lfs install

# Create virtual environment
RUN python3.10 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install wheel
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# Install PyTorch with CUDA support
RUN echo "🚀 Installing PyTorch with CUDA support..." && \
    pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install core dependencies
RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    httpx==0.27.0 \
    soundfile==0.12.1 \
    numpy \
    huggingface_hub \
    librosa>=0.10.0 \
    scipy>=1.9.0 \
    matplotlib>=3.5.0 \
    tqdm>=4.60.0

# Install MeCab dependencies
ENV MECAB_CONFIG=/usr/bin/mecab-config
RUN pip install --no-cache-dir fugashi[unidic-lite]==1.3.0 unidic-lite

# Install tokenizers and transformers (pinned versions)
ENV PIP_ONLY_BINARY=tokenizers
RUN pip install --no-cache-dir --no-build-isolation --only-binary=:all: tokenizers==0.13.3
RUN pip install --no-cache-dir transformers==4.27.4

# Install MeloTTS
RUN echo "📦 Installing MeloTTS..." && \
    pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Install OpenVoice V2 dependencies first
RUN echo "📦 Installing OpenVoice V2 dependencies..." && \
    pip install --no-cache-dir \
        monotonic_align>=0.1.2 \
        tensorboard>=2.8.0 \
        phonemizer>=3.2.0 \
        pypinyin>=0.50.0 \
        jieba>=0.42.1 \
        cn2an>=0.5.17 \
        inflect>=7.0.0 \
        unidecode>=1.3.7

# Install faster_whisper (this will install ctranslate2)
RUN echo "📦 Installing faster_whisper with ctranslate2..." && \
    pip install --no-cache-dir faster_whisper

# 🔧 CRITICAL FIX: Use patchelf to clear executable stack from ctranslate2 libraries
RUN echo "🔧 Fixing ctranslate2 executable stack issue..." && \
    # Find all ctranslate2 shared libraries and clear their executable stack
    find /opt/venv/lib/python3.10/site-packages/ctranslate2* -name "*.so*" -type f -exec patchelf --clear-execstack {} \; 2>/dev/null || true && \
    # Also fix any other potentially problematic libraries
    find /opt/venv/lib/python3.10/site-packages -name "*ctranslate2*.so*" -type f -exec patchelf --clear-execstack {} \; 2>/dev/null || true && \
    echo "✅ Executable stack cleared from ctranslate2 libraries"

# Test ctranslate2 import after the fix
RUN echo "🧪 Testing ctranslate2 import..." && \
    python -c "import ctranslate2; print('✅ ctranslate2 import successful after patchelf fix')" || \
    echo "⚠️ ctranslate2 import still has issues"

# Install OpenVoice V2
RUN echo "📦 Installing OpenVoice V2..." && \
    cd /tmp && \
    git clone --depth 1 https://github.com/myshell-ai/OpenVoice.git && \
    cd OpenVoice && \
    pip install --no-cache-dir . && \
    # Verify installation
    python -c "from openvoice.api import ToneColorConverter; print('✅ OpenVoice ToneColorConverter installed')" && \
    python -c "from openvoice import se_extractor; print('✅ OpenVoice se_extractor installed')" && \
    # Clean up
    cd / && rm -rf /tmp/OpenVoice

# Download unidic for Japanese support
RUN python -m unidic download || true

# Set working directory
WORKDIR /workspace

# Copy application files
COPY requirements.txt /workspace/
COPY setup_nltk.py /workspace/
COPY model_setup.py /workspace/
COPY shared/ /workspace/shared/
COPY app/ /workspace/app/

# Install any additional requirements
RUN pip install --no-cache-dir -r requirements.txt

# Create model directories
RUN mkdir -p /models/openvoice/checkpoints_v2/base_speakers && \
    mkdir -p /models/openvoice/checkpoints_v2/tone_color_converter

# Run model setup
RUN echo "📥 Downloading OpenVoice V2 models..." && \
    python /workspace/model_setup.py

# Run NLTK setup
RUN echo "📥 Setting up NLTK data..." && \
    python /workspace/setup_nltk.py

# Create non-root user and set permissions
RUN useradd -m -u 1001 appuser && \
    mkdir -p /home/appuser/.cache/huggingface/hub && \
    mkdir -p /home/appuser/.cache/torch && \
    mkdir -p /home/appuser/nltk_data && \
    chown -R appuser:appuser /workspace /home/appuser /models

# Set cache environment variables
ENV HF_HOME=/home/appuser/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface
ENV TORCH_HOME=/home/appuser/.cache/torch
ENV OPENVOICE_CHECKPOINTS_V2=/models/openvoice/checkpoints_v2
ENV NLTK_DATA=/home/appuser/nltk_data

# Set runtime environment
ENV PYTHONPATH="/workspace:/workspace/shared"
ENV HOST=0.0.0.0
ENV PORT=8000
ENV MELO_LANGUAGE=EN
ENV MELO_SPEAKER_ID=0
ENV CORS_ALLOW_ORIGINS="*"

# Switch to non-root user
USER appuser

# Final verification of the complete stack
RUN echo "🔍 Final verification:" && \
    python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}')" && \
    python -c "from melo.api import TTS; print('✅ MeloTTS imports OK')" && \
    python -c "from openvoice.api import ToneColorConverter; print('✅ OpenVoice ToneColorConverter OK')" && \
    python -c "from openvoice import se_extractor; print('✅ OpenVoice se_extractor OK')" && \
    python -c "import ctranslate2; print('✅ ctranslate2 OK')" && \
    python -c "import faster_whisper; print('✅ faster_whisper OK')" && \
    echo "🎉 Full OpenVoice V2 stack verified successfully!"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Expose port
EXPOSE 8000

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]