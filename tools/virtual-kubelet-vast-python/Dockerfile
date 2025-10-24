FROM python:3.10-slim

# Install system dependencies including SSL certificates
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    openssh-client \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Update CA certificates to fix SSL verification issues
RUN update-ca-certificates

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install vastai CLI with SSL certificate fixes
RUN pip install --no-cache-dir vastai || \
    (wget https://raw.githubusercontent.com/vast-ai/vast-python/master/vast.py -O /usr/local/bin/vastai && \
     chmod +x /usr/local/bin/vastai)

# Configure Python to use proper SSL certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Copy application code
COPY main.py .
COPY runtime_templates.py .

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