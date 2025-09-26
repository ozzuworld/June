# Clean Dockerfile for June Orchestrator
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements_clean.txt .
RUN pip install --no-cache-dir -r requirements_clean.txt

# Copy the clean application
COPY app_clean.py .

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "-m", "uvicorn", "app_clean:app", "--host", "0.0.0.0", "--port", "8000"]