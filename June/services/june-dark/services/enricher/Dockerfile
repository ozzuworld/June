FROM python:3.11-slim

LABEL maintainer="June Dark OSINT Team" 
LABEL description="Enricher - Data Processing and Enhancement Service"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    libpq-dev \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ./app /app

# Create logs directory
RUN mkdir -p /logs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:9010/health || exit 1

# Expose port
EXPOSE 9010

# Run application
CMD ["python", "-m", "main"]
