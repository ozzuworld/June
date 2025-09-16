# June/services/june-tts/Dockerfile - CHATTERBOX VERSION
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies including PyTorch and Chatterbox
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Download Chatterbox model during build (optional, can be done at runtime)
# RUN python -c "from chatterbox import Chatterbox; Chatterbox.from_pretrained('resemble-ai/chatterbox')"

# Set environment variables
ENV DEVICE=cpu \
    LOG_LEVEL=INFO \
    ENABLE_VOICE_CLONING=true \
    ENABLE_EMOTION_CONTROL=true

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/healthz || exit 1

# Expose port
EXPOSE 8080

# Start the application
CMD ["python", "app.py"]