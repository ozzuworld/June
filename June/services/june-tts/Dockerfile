# June/services/june-tts/Dockerfile - LIGHTWEIGHT PROXY
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    LOG_LEVEL=INFO \
    # External Chatterbox API (use hosted service)
    CHATTERBOX_API_URL=https://api.chatterboxtts.com \
    DEFAULT_VOICE=af_bella

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Run the proxy service
CMD ["python", "app.py"]