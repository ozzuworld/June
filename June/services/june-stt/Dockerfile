FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies for Whisper and audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    build-essential \
    pkg-config \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Install PyTorch (CPU version for smaller image, change if you need GPU)
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared module first (for auth) and install as package
COPY shared/ ./shared/
RUN pip install -e ./shared/

# Copy application code and environment file
COPY app.py .
COPY tts_client.py .

# ⭐ ADD THIS LINE - Copy .env file into the image
COPY .env .env

# Create non-root user and necessary directories
RUN useradd -m -u 1001 appuser && \
    mkdir -p /tmp && \
    chmod 755 /tmp && \
    chown -R appuser:appuser /app /tmp

USER appuser

# Health check - fixed port to match service
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Expose port
EXPOSE 8080

# Start the application directly
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]