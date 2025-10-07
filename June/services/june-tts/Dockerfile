FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Create directories (including matplotlib config)
RUN mkdir -p /tmp/transformers /tmp/huggingface /cache /models /tmp/matplotlib && \
    chmod 777 /tmp/transformers /tmp/huggingface /cache /models /tmp/matplotlib

# Set environment variables
ENV TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONPATH="/workspace"

# Install F5-TTS and dependencies
RUN pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    pydantic-settings \
    f5-tts \
    torch \
    torchaudio \
    transformers \
    soundfile \
    librosa \
    python-multipart \
    numpy

# Copy app
COPY . /workspace

# Test F5-TTS import
RUN python -c "from f5_tts.api import F5TTS; print('F5-TTS import: SUCCESS')"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
