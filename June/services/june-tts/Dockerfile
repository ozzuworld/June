# OpenVoice V2 TTS Service - Fixed for ctranslate2

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

# Install system dependencies (runtime + build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    pkg-config \
    libmecab-dev \
    mecab \
    mecab-ipadic-utf8 \
    libsndfile1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# CRITICAL: Install ctranslate2 with proper flags
# Use pre-built wheels to avoid compilation issues
RUN pip install --no-cache-dir \
    ctranslate2>=3.24.0 \
    faster-whisper>=1.0.0

# Install MeloTTS and OpenVoice
RUN pip install --no-cache-dir \
    git+https://github.com/myshell-ai/MeloTTS.git \
    git+https://github.com/myshell-ai/OpenVoice.git

# Download unidic for Japanese
RUN python -m unidic download || true

# Copy application code
COPY app/ ./app/
COPY model_setup.py setup_nltk.py ./

# Setup NLTK and models
RUN python setup_nltk.py && \
    mkdir -p /models/openvoice/checkpoints_v2 && \
    python model_setup.py || echo "⚠️ Model download partial, will retry at runtime"

# Create non-root user and home directory with proper permissions
RUN useradd -m -u 1001 appuser && \
    mkdir -p /home/appuser/.cache /home/appuser/.numba_cache && \
    chown -R appuser:appuser /workspace /models /home/appuser

USER appuser

# Environment variables for cache and ctranslate2
ENV NUMBA_CACHE_DIR=/home/appuser/.numba_cache \
    MPLCONFIGDIR=/home/appuser/.matplotlib \
    HF_HOME=/home/appuser/.cache/huggingface \
    CT2_VERBOSE=0

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

ENV OPENVOICE_CHECKPOINTS_V2=/models/openvoice/checkpoints_v2 \
    OPENVOICE_DEVICE=cuda \
    PYTHONPATH=/workspace

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]