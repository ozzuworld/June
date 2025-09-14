# services/june-kokoro-tts/Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    espeak-ng \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Kokoro model and voices
RUN mkdir -p /app/models && \
    cd /app/models && \
    git lfs install && \
    git clone https://huggingface.co/hexgrad/Kokoro-82M . && \
    ls -la

# Copy application code
COPY . .

# Expose port
EXPOSE 8080

# Start the service
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]