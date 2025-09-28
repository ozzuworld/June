# Fixed OpenVoice V2 Dockerfile - Solution 4: Alternative Base Image
# This approach uses an older/compatible base image that doesn't have the ctranslate2 issue
FROM ubuntu:20.04

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV TZ=UTC

# Install Python 3.10 and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python 3.10 installation
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3.10-venv \
    python3.10-distutils \
    # System dependencies
    curl \
    wget \
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

# Install pip for Python 3.10
RUN curl https://bootstrap.pypa.io/get-pip.py | python3.10

# Create virtual environment with Python 3.10
RUN python3.10 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install wheel
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# Install PyTorch with CUDA support (compatible with Ubuntu 20.04)
RUN echo "🚀 Installing PyTorch with CUDA support..." && \
    pip install --no-cache-dir torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118

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

# Install older compatible versions of tokenizers and transformers
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

# Install compatible version of faster_whisper (older version that works with Ubuntu 20.04)
RUN echo "📦 Installing compatible faster_whisper..." && \
    pip install --no-cache-dir faster_whisper==0.9.0

# Install OpenVoice V2 (should work with older glibc in Ubuntu 20.04)
RUN echo "📦 Installing OpenVoice V2..." && \
    cd /tmp && \
    git clone --depth 1 https://github.com/myshell-ai/OpenVoice.git && \
    cd OpenVoice && \
    # Regular install should work with Ubuntu 20.04's older glibc
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

# Install any additional requirements from your requirements.txt
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

# Final verification
RUN echo "🔍 Final verification:" && \
    python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}')" && \
    python -c "from melo.api import TTS; print('✅ MeloTTS imports OK')" && \
    python -c "from openvoice.api import ToneColorConverter; print('✅ OpenVoice ToneColorConverter OK')" && \
    python -c "from openvoice import se_extractor; print('✅ OpenVoice se_extractor OK')" && \
    python -c "import ctranslate2; print('✅ ctranslate2 OK')" && \
    python -c "import faster_whisper; print('✅ faster_whisper OK')" && \
    echo "🎉 Full OpenVoice V2 stack verified successfully on Ubuntu 20.04!"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Expose port
EXPOSE 8000

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]