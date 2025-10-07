FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . /workspace

# Test F5-TTS import
RUN python -c "from f5_tts.api import F5TTS; print('✅ F5-TTS API import successful')"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
