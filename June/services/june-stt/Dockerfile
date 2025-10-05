# ===== MULTI-STAGE BUILD FOR MINIMAL IMAGE =====

# Stage 1: Build stage with full tools
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    cmake \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install Python dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# ===== Stage 2: Production runtime (minimal) =====
FROM python:3.11-slim as runtime

# Install only runtime dependencies (no build tools)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && rm -rf /tmp/* /var/tmp/*

# Create non-root user for security
RUN groupadd -r stt && useradd -r -g stt -u 1001 stt

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code (only what's needed)
COPY --chown=stt:stt config.py .
COPY --chown=stt:stt whisper_service.py .
COPY --chown=stt:stt orchestrator_client.py .
COPY --chown=stt:stt app.py .

# Create directories with proper permissions
RUN mkdir -p /app/models /tmp && \
    chown -R stt:stt /app /tmp

# Switch to non-root user
USER stt

# Expose port
EXPOSE 8080

# Health check (optimized)
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Set environment variables for optimization
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    OMP_NUM_THREADS=4

# Run application
CMD ["python", "app.py"]
