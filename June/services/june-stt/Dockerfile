# WhisperX Enhanced June STT Service - cuDNN 9 Compatible
# Based on official WhisperX requirements and best practices
# Reference: https://github.com/m-bain/whisperX
# Updated for cuDNN 9 compatibility to fix CTranslate2 issues

# Use CUDA 12.3+ base image for cuDNN 9 compatibility
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04 AS runtime

# Environment setup
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

# Metadata
LABEL maintainer="ozzuworld <eng.ozzu@icloud.com>"
LABEL version="8.2.0-whisperx-cudnn9"
LABEL description="June STT with WhisperX - cuDNN 9 Compatible"
LABEL service="june-stt"
LABEL framework="whisperx"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3-pip \
    ffmpeg \
    libsndfile1 \
    sox \
    libsox-dev \
    curl \
    wget \
    git \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic links for Python
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Create app directory and user
RUN useradd -m -u 1001 sttuser
WORKDIR /app
RUN chown -R sttuser:sttuser /app

# Install PyTorch with CUDA 12.4 support for cuDNN 9 compatibility
# Updated to support latest CTranslate2 versions
RUN pip install --no-cache-dir \
    torch==2.4.0 \
    torchaudio==2.4.0 \
    --index-url https://download.pytorch.org/whl/cu124

# Copy requirements and install dependencies
COPY --chown=sttuser:sttuser requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=sttuser:sttuser main.py /app/
COPY --chown=sttuser:sttuser config.py /app/
COPY --chown=sttuser:sttuser whisper_service.py /app/
COPY --chown=sttuser:sttuser livekit_token.py /app/
COPY --chown=sttuser:sttuser orchestrator_client.py /app/
COPY --chown=sttuser:sttuser streaming_utils.py /app/
COPY --chown=sttuser:sttuser context_aware_stt.py /app/

# Set up environment
ENV PYTHONPATH=/app
USER sttuser

# Create necessary directories
RUN mkdir -p /app/models /app/cache /app/temp

# WhisperX Environment Configuration
ENV WHISPER_CACHE_DIR=/app/models
ENV PORT=8001
ENV LOG_LEVEL=INFO

# WhisperX Model Configuration
ENV WHISPER_MODEL=large-v3-turbo
ENV USE_BATCHED_INFERENCE=true
ENV ENABLE_WORD_TIMESTAMPS=true

# Silero VAD Preprocessing
ENV SILERO_VAD_ENABLED=true
ENV VAD_ENABLED=false

# Language & Accent Optimization
ENV DEFAULT_LANGUAGE=en
ENV FORCE_LANGUAGE=true
ENV ACCENT_OPTIMIZATION=true
ENV INITIAL_PROMPT="English speech with Latino accent. Technical vocabulary: Kubernetes, Docker, API, microservices, Redis, database. Mathematical terms: square root, calculations, numbers."

# WhisperX Streaming Features
ENV SOTA_MODE_ENABLED=true
ENV ULTRA_FAST_PARTIALS=true
ENV WORD_LEVEL_PARTIALS=true
ENV STT_STREAMING_ENABLED=true
ENV STT_PARTIALS_ENABLED=true
ENV STT_CONTINUOUS_PARTIALS=true

# cuDNN 9 Library Path (additional safety)
ENV LD_LIBRARY_PATH="/usr/local/lib/python3.10/dist-packages/nvidia/cudnn/lib:$LD_LIBRARY_PATH"

EXPOSE 8001

# Enhanced health check for WhisperX
HEALTHCHECK --interval=20s --timeout=15s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8001/healthz | grep -q '"framework":"whisperx"' || exit 1

# Startup command
CMD ["python", "main.py"]