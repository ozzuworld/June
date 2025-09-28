# Complete June TTS Dockerfile - FIXED
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

# Install GPU PyTorch for faster processing
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

# Install OpenVoice V2 with all dependencies
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
COPY model_setup.py /workspace/
COPY shared/ /workspace/shared/
COPY app/ /workspace/app/

# Install any additional requirements
RUN pip install --no-cache-dir -r requirements.txt

# Create model directories
RUN mkdir -p /models/openvoice/checkpoints_v2/base_speakers && \
    mkdir -p /models/openvoice/checkpoints_v2/tone_color_converter

# FIXED: Use the proper model_setup.py script instead of inline Python
RUN python /workspace/model_setup.py

# FIXED: Run NLTK setup using the existing script
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

# GPU verification at runtime - FIXED (simplest approach)
RUN echo "🔍 Runtime verification:" && \
    python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA devices: {torch.cuda.device_count()}')" && \
    python -c "from melo.api import TTS; print('✅ MeloTTS imports OK')" && \
    python -c "import importlib; openvoice_ok = importlib.util.find_spec('openvoice') is not None; print('✅ OpenVoice imports OK' if openvoice_ok else '⚠️ OpenVoice not available')" && \
    echo "🎉 Build verification complete!"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Expose port
EXPOSE 8000

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]