FROM python:3.11-slim

LABEL maintainer="June Dark OSINT Team"
LABEL description="Enricher - Data processing and enrichment service"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    exiftool \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    pydantic==2.9.2 \
    pydantic-settings==2.5.2 \
    httpx==0.27.2 \
    elasticsearch==8.15.1 \
    neo4j==5.24.0 \
    psycopg[binary]==3.2.2 \
    pika==1.3.2 \
    redis==5.1.0 \
    minio==7.2.9 \
    trafilatura==1.12.0 \
    beautifulsoup4==4.12.3 \
    lxml==5.3.0 \
    pdfplumber==0.11.4 \
    python-magic==0.4.27 \
    pillow==10.4.0 \
    python-whois==0.8.0

WORKDIR /app

# Copy application code
COPY ./app /app

# Create necessary directories
RUN mkdir -p /artifacts /logs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:9010/health || exit 1

# Expose port
EXPOSE 9010

# Run worker and API
CMD ["python", "-m", "main"]