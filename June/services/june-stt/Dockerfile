# Use bullseye to get an FFmpeg version compatible with PyAV 11
FROM python:3.10-slim-bullseye

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies, including FFmpeg + dev libs for PyAV
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
    libavfilter-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Get whisper_streaming helper
RUN git clone --depth 1 https://github.com/ufal/whisper_streaming.git /tmp/whisper_streaming && \
    cp /tmp/whisper_streaming/whisper_online.py /app/ && \
    rm -rf /tmp/whisper_streaming

# App code
COPY main.py .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

CMD ["python", "main.py"]
