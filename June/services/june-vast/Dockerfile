# June vast.ai combined STT+TTS image with official faster-whisper GPU setup
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda \
    PATH=/usr/local/cuda/bin:$PATH

# Base system deps (both services)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip \
    ffmpeg espeak-ng libsndfile1 libportaudio2 \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create separate virtualenvs to avoid dependency conflicts
RUN python3.10 -m venv /venv-stt && python3.10 -m venv /venv-tts

# Copy requirements
COPY June/services/june-stt/requirements.txt /tmp/stt-requirements.txt
COPY June/services/june-tts/requirements.txt /tmp/tts-requirements.txt

# STT deps with official faster-whisper GPU libraries
RUN /venv-stt/bin/pip install --upgrade pip setuptools wheel && \
    /venv-stt/bin/pip install "numpy<2.0" && \
    /venv-stt/bin/pip install torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 \
      --index-url https://download.pytorch.org/whl/cu121 && \
    /venv-stt/bin/pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.* && \
    /venv-stt/bin/pip install -r /tmp/stt-requirements.txt && \
    rm -rf /root/.cache

# TTS deps with CUDA 12.3 compatibility
RUN /venv-tts/bin/pip install --upgrade pip setuptools wheel && \
    /venv-tts/bin/pip install "numpy<2.0" && \
    /venv-tts/bin/pip install torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 \
      --index-url https://download.pytorch.org/whl/cu121 && \
    /venv-tts/bin/pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.* && \
    /venv-tts/bin/pip install -r /tmp/tts-requirements.txt && \
    rm -rf /root/.cache

# Copy application code
COPY June/services/june-stt/ /app/stt/
COPY June/services/june-tts/ /app/tts/

# Runtime env with CUDA library paths
ENV TTS_CACHE_PATH=/app/cache \
    TTS_HOME=/app/models \
    WHISPER_CACHE_DIR=/app/models \
    COQUI_TOS_AGREED=1 \
    STT_PORT=8001 \
    TTS_PORT=8000

# Set library path for CUDA/cuDNN from pip-installed packages
RUN echo '#!/bin/bash\n\
export CUBLAS_PATH=$(/venv-stt/bin/python -c "import nvidia.cublas.lib; print(os.path.dirname(nvidia.cublas.lib.__file__))" 2>/dev/null || echo "")\n\
export CUDNN_PATH=$(/venv-stt/bin/python -c "import nvidia.cudnn.lib; print(os.path.dirname(nvidia.cudnn.lib.__file__))" 2>/dev/null || echo "")\n\
if [ -n "$CUBLAS_PATH" ] && [ -n "$CUDNN_PATH" ]; then\n\
    export LD_LIBRARY_PATH="$CUBLAS_PATH:$CUDNN_PATH:$LD_LIBRARY_PATH"\n\
fi\n\
exec "$@"' > /app/cuda-setup.sh && chmod +x /app/cuda-setup.sh

# Expose service ports
EXPOSE 8000 8001

# Add entrypoint script that starts both services
COPY June/services/june-vast/start-both.sh /app/start-both.sh
RUN chmod +x /app/start-both.sh

ENTRYPOINT ["/app/cuda-setup.sh", "/app/start-both.sh"]