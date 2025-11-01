# Kokoro TTS Ultra-Low Latency Container (PyTorch minimal)
FROM pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime

# Install system dependencies for audio
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PYTHONUNBUFFERED=1
ENV TTS_STREAMING_ENABLED=true

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["python", "main.py"]
