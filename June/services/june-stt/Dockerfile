FROM python:3.10-slim

# Install system dependencies for LiveKit SDK and audio processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    pkg-config \
    build-essential \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libavdevice-dev \
    libavfilter-dev \
    libswscale-dev \
    libswresample-dev \
    portaudio19-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies (LiveKit SDK needs the above system packages)
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create models directory for Whisper
RUN mkdir -p /app/models

# Expose port
EXPOSE 8080

# Set environment variables
ENV PYTHONPATH=/app
ENV PORT=8080
ENV WHISPER_CACHE=/app/models

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Run the application
CMD ["python", "main.py"]