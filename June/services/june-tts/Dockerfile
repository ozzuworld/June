# Kokoro TTS GPU Container (CUDA 12.1, no torchvision)
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

# System deps
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    espeak-ng \
    python3.10 \
    python3.10-venv \
    python3-pip \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Virtual env
RUN python3.10 -m venv /venv-tts
ENV PATH="/venv-tts/bin:$PATH"

# Copy and install GPU torch first (CUDA wheels), then app deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip install --no-cache-dir \
    torch==2.2.2+cu121 torchaudio==2.2.2+cu121 \
    --index-url https://download.pytorch.org/whl/cu121 \
 && pip install --no-cache-dir -r /app/requirements.txt

# Copy app
COPY . /app

ENV PYTHONUNBUFFERED=1
ENV TTS_STREAMING_ENABLED=true

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["python", "main.py"]
