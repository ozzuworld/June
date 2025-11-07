# Whisper-Streaming June STT Service - Real-Time Transcription
# Implements UFAL whisper_streaming for <3.3s latency
# Reference: https://github.com/ufal/whisper_streaming

FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04 AS runtime

# Environment setup
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

# Metadata
LABEL maintainer="ozzuworld <eng.ozzu@icloud.com>"
LABEL version="9.0.0-whisper-streaming"
LABEL description="June STT with Whisper-Streaming - Real-Time (<3.3s latency)"
LABEL service="june-stt"
LABEL framework="whisper-streaming"

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

# Install PyTorch with CUDA 12.4 support (required for Silero VAD)
RUN pip install --no-cache-dir \
    torch==2.4.0 \
    torchaudio==2.4.0 \
    --index-url https://download.pytorch.org/whl/cu124

# Copy requirements and install base dependencies
COPY --chown=sttuser:sttuser requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Install whisper-streaming from GitHub (not on PyPI)
RUN pip install --no-cache-dir git+https://github.com/ufal/whisper_streaming

# Copy application code
COPY --chown=sttuser:sttuser main_streaming.py /app/
COPY --chown=sttuser:sttuser config.py /app/
COPY --chown=sttuser:sttuser whisper_streaming_service.py /app/
COPY --chown=sttuser:sttuser livekit_token.py /app/
COPY --chown=sttuser:sttuser streaming_utils.py /app/

# Set up environment
ENV PYTHONPATH=/app
USER sttuser

# Create necessary directories
RUN mkdir -p /app/models /app/cache /app/temp

# Whisper-Streaming Configuration
ENV WHISPER_CACHE_DIR=/app/models
ENV PORT=8001
ENV LOG_LEVEL=INFO

# Model Configuration
ENV WHISPER_MODEL=large-v3-turbo
ENV DEFAULT_LANGUAGE=en
ENV FORCE_LANGUAGE=true

# Streaming Configuration
ENV MIN_CHUNK_SIZE=1.0
ENV BUFFER_TRIMMING_SEC=15.0
ENV VAC_CHUNK_SIZE=0.5

# LiveKit & Orchestrator
ENV LIVEKIT_ENABLED=true
ENV ORCHESTRATOR_ENABLED=true

# cuDNN Library Path
ENV LD_LIBRARY_PATH="/usr/local/lib/python3.10/dist-packages/nvidia/cudnn/lib:$LD_LIBRARY_PATH"

EXPOSE 8001

# Health check for whisper-streaming
HEALTHCHECK --interval=20s --timeout=15s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8001/healthz | grep -q '"framework":"whisper-streaming"' || exit 1

# Run main_streaming.py
CMD ["python", "main_streaming.py"]
