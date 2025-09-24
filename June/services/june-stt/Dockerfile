FROM python:3.11-slim

# Install ffmpeg for on-the-fly audio conversion
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Add this before COPY . . in each Dockerfile
COPY ../shared /shared
RUN pip install -e /shared

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Cloud Run listens on $PORT (default 8080). We can hardcode 8080 safely.
EXPOSE 8080

# Start FastAPI app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
