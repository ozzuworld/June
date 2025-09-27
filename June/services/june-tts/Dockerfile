# Simplified June TTS Dockerfile - Basic TTS functionality
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    libsndfile1 \
    pkg-config \
    mecab \
    libmecab-dev \
    mecab-ipadic-utf8 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Create models directory structure
RUN mkdir -p /models/openvoice/checkpoints_v2/tone_color_converter

# Copy shared module first
COPY shared/ /workspace/shared/
RUN pip install -e /workspace/shared/

# Copy and install requirements
COPY requirements.txt /workspace/
RUN pip install --no-cache-dir -r requirements.txt

# Install MeloTTS (main TTS engine)
RUN pip install git+https://github.com/myshell-ai/MeloTTS.git

# Set up MeCab environment
ENV MECAB_CONFIG=/usr/bin/mecab-config

# Copy application files
COPY app/ /workspace/app/
COPY *.py /workspace/

# Set environment variables
ENV PYTHONPATH="/workspace:/workspace/shared"
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8000
ENV MELO_LANGUAGE=EN
ENV MELO_SPEAKER_ID=0
ENV CORS_ALLOW_ORIGINS="*"

# Create non-root user
RUN groupadd -r appuser && \
    useradd -r -g appuser appuser && \
    chown -R appuser:appuser /workspace /models

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Expose port
EXPOSE 8000

# Switch to non-root user
USER appuser

# Start command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]