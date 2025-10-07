FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

# Install Python and system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    git \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with proper permissions
RUN groupadd -r sttuser && useradd -r -g sttuser sttuser

# Create directories with proper ownership
RUN mkdir -p /app /tmp/models /tmp/huggingface && \
    chown -R sttuser:sttuser /app /tmp/models /tmp/huggingface

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
RUN chown -R sttuser:sttuser /app

# Set environment variables for model caching
ENV TRANSFORMERS_CACHE=/tmp/models
ENV HF_HOME=/tmp/huggingface
ENV PYTHONPATH=/app

# Switch to non-root user
USER sttuser

# Expose port
EXPOSE 8080

# Start the service
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
