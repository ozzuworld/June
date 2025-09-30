FROM python:3.11-slim

LABEL maintainer="June Dark OSINT Team"
LABEL description="Ops UI - Monitoring and operations dashboard"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    jinja2==3.1.4 \
    httpx==0.27.2 \
    pydantic==2.9.2 \
    pydantic-settings==2.5.2 \
    elasticsearch==8.15.1 \
    redis==5.1.0 \
    pika==1.3.2

WORKDIR /app

# Copy application code
COPY ./app /app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8090/health || exit 1

# Expose port
EXPOSE 8090

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]