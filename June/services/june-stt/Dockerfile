FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for optimal performance
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV CTRANSLATE2_CACHE_DIRECTORY=/app/models
ENV HF_HOME=/app/cache
ENV WHISPER_CACHE_DIR=/app/models

# Create app directories
WORKDIR /app
RUN mkdir -p /app/models /app/cache /tmp

# Install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip
RUN pip3 install --no-cache-dir -r requirements.txt

# Pre-download model files ONLY (not load into memory with GPU)
# This just downloads the model files to cache - GPU loading happens at runtime
RUN python3 -c "from faster_whisper import WhisperModel; print('📥 Pre-downloading model files...'); WhisperModel('large-v3', device='cpu', download_root='/app/models'); print('✅ Model files cached')"

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Expose port
EXPOSE 8000

# At runtime, the app will detect GPU and use:
# device='cuda', compute_type='float16' for actual inference
CMD ["python3", "app.py"]
