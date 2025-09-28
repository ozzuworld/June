# Fixed OpenVoice V2 Dockerfile - Solution 3: Runtime Environment Fix
# This approach uses runtime environment variables to bypass the executable stack issue
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# 🔧 CRITICAL: Set glibc runtime tunable to allow executable stack
ENV GLIBC_TUNABLES=glibc.rtld.execstack=2

# Install ALL dependencies
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

# Install OpenVoice V2 dependencies
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

# 🔧 Install OpenVoice V2 with runtime environment fix
RUN echo "📦 Installing OpenVoice V2 with runtime fix..." && \
    cd /tmp && \
    git clone --depth 1 https://github.com/myshell-ai/OpenVoice.git && \
    cd OpenVoice && \
    # Install with the glibc tunable set
    GLIBC_TUNABLES=glibc.rtld.execstack=2 pip install --no-cache-dir . && \
    # Verify installation with runtime fix
    GLIBC_TUNABLES=glibc.rtld.execstack=2 python -c "from openvoice.api import ToneColorConverter; print('✅ OpenVoice ToneColorConverter installed')" && \
    GLIBC_TUNABLES=glibc.rtld.execstack=2 python -c "from openvoice import se_extractor; print('✅ OpenVoice se_extractor installed')" && \
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

# Run model setup with runtime fix
RUN echo "📥 Downloading OpenVoice V2 models..." && \
    GLIBC_TUNABLES=glibc.rtld.execstack=2 python /workspace/model_setup.py

# Run NLTK setup
RUN echo "📥 Setting up NLTK data..." && \
    python /workspace/setup_nltk.py

# Create startup script that sets the runtime environment
RUN echo '#!/bin/bash\n\
# Set the glibc tunable to allow executable stack for ctranslate2\n\
export GLIBC_TUNABLES=glibc.rtld.execstack=2\n\
\n\
# Start the application with the environment fix\n\
exec "$@"\n\
' > /workspace/entrypoint.sh && \
    chmod +x /workspace/entrypoint.sh

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

# Final verification with runtime fix
RUN echo "🔍 Final verification:" && \
    GLIBC_TUNABLES=glibc.rtld.execstack=2 python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}')" && \
    GLIBC_TUNABLES=glibc.rtld.execstack=2 python -c "from melo.api import TTS; print('✅ MeloTTS imports OK')" && \
    GLIBC_TUNABLES=glibc.rtld.execstack=2 python -c "from openvoice.api import ToneColorConverter; print('✅ OpenVoice ToneColorConverter OK')" && \
    GLIBC_TUNABLES=glibc.rtld.execstack=2 python -c "from openvoice import se_extractor; print('✅ OpenVoice se_extractor OK')" && \
    echo "🎉 All components verified successfully with runtime fix!"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Expose port
EXPOSE 8000

# Use entrypoint script to set runtime environment
ENTRYPOINT ["/workspace/entrypoint.sh"]

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]