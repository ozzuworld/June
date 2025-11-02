# SOTA June STT - Using faster-whisper-server as base with large-v3-turbo optimization
# Multi-stage build combining faster-whisper-server optimizations with LiveKit integration
# Upgraded for competitive transcription accuracy matching OpenAI/Google standards

# Stage 1: Get faster-whisper-server functionality
FROM fedirz/faster-whisper-server:latest-cuda AS whisper-base

# Stage 2: Build SOTA enhanced service
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 AS runtime

# Environment setup
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$PATH:/usr/local/cuda/bin
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

# SOTA Image metadata
LABEL maintainer="ozzuworld <eng.ozzu@icloud.com>"
LABEL version="7.0.0-sota-competitive"
LABEL description="June STT SOTA - large-v3-turbo + accent optimization + ultra-fast streaming"
LABEL service="june-stt"
LABEL optimization="SOTA_COMPETITIVE"

# Copy faster-whisper-server Python environment and dependencies
COPY --from=whisper-base /usr/local/lib/python*/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=whisper-base /usr/local/bin /usr/local/bin

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    ffmpeg \
    libsndfile1 \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic links for Python
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# Create app directory and user
RUN useradd -m -u 1001 sttuser
WORKDIR /app
RUN chown -R sttuser:sttuser /app

# Install additional dependencies for LiveKit integration
COPY --chown=sttuser:sttuser requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy SOTA application code
COPY --chown=sttuser:sttuser main.py /app/
COPY --chown=sttuser:sttuser config.py /app/
COPY --chown=sttuser:sttuser whisper_service.py /app/
COPY --chown=sttuser:sttuser livekit_token.py /app/
COPY --chown=sttuser:sttuser orchestrator_client.py /app/
COPY --chown=sttuser:sttuser streaming_utils.py /app/
COPY --chown=sttuser:sttuser README.md /app/

# Set up environment
ENV PYTHONPATH=/app
USER sttuser

# Create necessary directories
RUN mkdir -p /app/models /app/cache /app/temp

# SOTA Environment configuration - Optimized for competitive accuracy
ENV WHISPER_CACHE_DIR=/app/models
ENV PORT=8001
ENV LOG_LEVEL=INFO

# SOTA MODEL CONFIGURATION - Upgraded for competitive accuracy
ENV WHISPER_MODEL=large-v3-turbo
ENV USE_BATCHED_INFERENCE=true
ENV VAD_ENABLED=false
ENV SILERO_VAD_ENABLED=true

# SOTA ACCURACY OPTIMIZATION - English forcing + accent handling
ENV DEFAULT_LANGUAGE=en
ENV FORCE_LANGUAGE=true
ENV ACCENT_OPTIMIZATION=true
ENV INITIAL_PROMPT="English speech with Latin accent. Mathematical terms: square root, calculations, numbers. Technical vocabulary."

# SOTA STREAMING OPTIMIZATION - Ultra-fast partial processing
ENV SOTA_MODE_ENABLED=true
ENV ULTRA_FAST_PARTIALS=true
ENV AGGRESSIVE_VAD_TUNING=true
ENV STT_STREAMING_ENABLED=true
ENV STT_PARTIALS_ENABLED=true
ENV STT_CONTINUOUS_PARTIALS=true

EXPOSE 8001

# SOTA health check - Enhanced for competitive monitoring
HEALTHCHECK --interval=20s --timeout=15s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8001/healthz | grep -q '"optimization":"SOTA_VOICE_AI_COMPETITIVE"' || exit 1

# SOTA startup command
CMD ["python", "main.py"]