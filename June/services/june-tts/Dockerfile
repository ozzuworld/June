# June TTS Service with F5-TTS and Voice Cloning
# TTS-only image. No WhisperX/faster-whisper/av.

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda \
    PATH=$PATH:/usr/local/cuda/bin \
    LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64

LABEL maintainer="ozzuworld <eng.ozzu@icloud.com>"
LABEL version="1.0.3-tts-stable"
LABEL description="June TTS (CosyVoice2/F5-TTS) - no STT deps"
LABEL service="june-tts"
LABEL framework="cosyvoice2"

# Minimal system deps for TTS
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3-pip \
    libsndfile1 sox libsox-dev \
    curl wget git build-essential cmake unzip \
    ffmpeg \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

RUN useradd -m -u 1001 sttuser
WORKDIR /app
RUN chown -R sttuser:sttuser /app

# Torch with CUDA 12.1
RUN pip install --no-cache-dir \
    torch==2.2.0 torchaudio==2.2.0 \
    --index-url https://download.pytorch.org/whl/cu121

# Copy requirements and install (no constraints file)
COPY --chown=sttuser:sttuser requirements.txt /app/
RUN pip install --no-cache-dir --prefer-binary --default-timeout=3600 -r requirements.txt

# Copy app code
COPY --chown=sttuser:sttuser *.py /app/

ENV PYTHONPATH=/app
USER sttuser

RUN mkdir -p /app/models /app/cache /app/temp

ENV PORT=8002 \
    LOG_LEVEL=INFO \
    TTS_MODEL=f5-tts \
    VOICE_CLONING_ENABLED=true \
    STREAMING_ENABLED=true \
    BATCH_SIZE=1 \
    LIVEKIT_ENABLED=true

EXPOSE 8002

HEALTHCHECK --interval=20s --timeout=15s --start-period=120s --retries=3 \
  CMD curl -f http://localhost:8002/healthz || exit 1

CMD ["python", "main.py"]