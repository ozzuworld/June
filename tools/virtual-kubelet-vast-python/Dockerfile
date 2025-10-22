FROM python:3.11-slim

# Install system dependencies including SSH client
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install vastai CLI - try pip first, fallback to direct download
RUN pip install --no-cache-dir vastai || \
    (wget https://raw.githubusercontent.com/vast-ai/vast-python/master/vast.py -O /usr/local/bin/vastai && \
     chmod +x /usr/local/bin/vastai)

# Copy application code
COPY main.py .

# Create non-root user
RUN useradd --create-home --shell /bin/bash vk
USER vk

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:10255/healthz || exit 1

# Expose health check port
EXPOSE 10255

# Run the Virtual Kubelet
CMD ["python", "main.py"]