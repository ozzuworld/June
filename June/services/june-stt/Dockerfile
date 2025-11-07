FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies (including PyAV build deps)
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    libsndfile1 \
    pkg-config \
    build-essential \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Clone whisper_streaming repository
RUN git clone https://github.com/ufal/whisper_streaming.git /tmp/whisper_streaming

# Copy whisper_streaming modules to our app
RUN cp /tmp/whisper_streaming/whisper_online.py /app/ && \
    rm -rf /tmp/whisper_streaming

# Copy application code
COPY main.py .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

CMD ["python", "main.py"]
