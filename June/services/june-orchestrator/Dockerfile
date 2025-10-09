# Multi-stage build to keep final image small
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies (needed for webrtcvad, aiortc, av)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    pkg-config \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    libavfilter-dev \
    libopus-dev \
    libvpx-dev \
    libsrtp2-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies with CORRECT version numbers for Debian Trixie
RUN apt-get update && apt-get install -y \
    curl \
    libavformat61 \
    libavcodec61 \
    libavdevice61 \
    libavutil59 \
    libswscale8 \
    libswresample5 \
    libavfilter10 \
    libopus0 \
    libvpx9 \
    libsrtp2-1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code in clean structure
COPY app/ ./app/
COPY .env .env

# Create non-root user for security
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Expose port
EXPOSE 8080

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Run the application
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
