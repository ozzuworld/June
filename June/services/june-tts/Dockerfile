# Kokoro TTS Ultra-Low Latency Container
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    wget \
    curl \
    ffmpeg \
    libsndfile1 \
    libsndfile1-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create virtual environment
RUN python -m venv /venv-tts
ENV PATH="/venv-tts/bin:$PATH"

# Copy and install requirements
COPY requirements.txt /tmp/tts-requirements.txt

# Install Kokoro TTS dependencies
RUN /venv-tts/bin/pip install --upgrade pip setuptools wheel && \
    /venv-tts/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 && \
    /venv-tts/bin/pip install -r /tmp/tts-requirements.txt

# Copy application code
COPY . .

# Environment variables
ENV PYTHONPATH=/app
ENV CUDA_VISIBLE_DEVICES=0
ENV TTS_STREAMING_ENABLED=true

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

# Run Kokoro TTS service
CMD ["python", "main.py"]