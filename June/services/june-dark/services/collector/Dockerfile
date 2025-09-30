FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

LABEL maintainer="June Dark OSINT Team"
LABEL description="Collector - Web scraping and data collection service"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    scrapy==2.11.2 \
    playwright==1.47.0 \
    httpx==0.27.2 \
    requests==2.32.3 \
    redis==5.1.0 \
    pika==1.3.2 \
    beautifulsoup4==4.12.3 \
    trafilatura==1.12.0 \
    minio==7.2.9 \
    lxml==5.3.0 \
    pillow==10.4.0 \
    python-magic==0.4.27 \
    fake-useragent==1.5.1 \
    pydantic==2.9.2 \
    pydantic-settings==2.5.2

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

WORKDIR /app

# Copy application code
COPY ./app /app

# Create necessary directories
RUN mkdir -p /artifacts /logs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Run the collector worker
CMD ["python", "-m", "main"]