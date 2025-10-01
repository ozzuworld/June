FROM python:3.10-slim

LABEL maintainer="June Dark OSINT Team"
LABEL description="Collector - Data Collection and Crawling Service"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ./app /app

# Create logs directory
RUN mkdir -p /logs

# Expose port (if needed)
EXPOSE 9020

# Run application
CMD ["python", "-m", "main"]
