# June TTS Service - CosyVoice2 Only
FROM nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda \
    PATH=$PATH:/usr/local/cuda/bin \
    LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

LABEL maintainer="ozzuworld <eng.ozzu@icloud.com>"
LABEL version="1.0.6-cosyvoice2-stable"
LABEL description="June TTS (CosyVoice2) - with automatic model download"
LABEL service="june-tts"
LABEL framework="cosyvoice2"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3-pip \
    libsndfile1 sox libsox-dev \
    curl wget git git-lfs build-essential cmake unzip \
    sudo ffmpeg \
 && git lfs install \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Create user
RUN useradd -m -u 1001 sttuser
WORKDIR /app
RUN chown -R sttuser:sttuser /app

# Allow sttuser to run chown via sudo for permission fixes
RUN echo "sttuser ALL=(ALL) NOPASSWD: /bin/chown" >> /etc/sudoers

# Install PyTorch with CUDA 12.1
RUN pip install --no-cache-dir \
    torch==2.2.0 torchaudio==2.2.0 \
    --index-url https://download.pytorch.org/whl/cu121

# Clone CosyVoice and install dependencies
RUN mkdir -p /opt && cd /opt && \
    git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git && \
    cd CosyVoice && git submodule update --init --recursive && \
    pip install --no-cache-dir -r requirements.txt

# Set Python path for CosyVoice imports
ENV PYTHONPATH=/opt/CosyVoice/third_party/Matcha-TTS:/opt/CosyVoice:/app:${PYTHONPATH}

# Install service dependencies
COPY --chown=sttuser:sttuser requirements.txt /app/
RUN pip install --no-cache-dir --prefer-binary --default-timeout=3600 -r requirements.txt

# Copy application code
COPY --chown=sttuser:sttuser *.py /app/
COPY --chown=sttuser:sttuser startup.sh /app/
RUN chmod +x /app/startup.sh

USER sttuser

# Create necessary directories
RUN mkdir -p /app/pretrained_models /app/cache /app/temp

# Environment variables
ENV SERVICE_PORT=8000 \
    LOG_LEVEL=INFO \
    MODEL_DIR=/app/pretrained_models \
    LIVEKIT_ENABLED=true

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=15s --start-period=240s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["/app/startup.sh"]