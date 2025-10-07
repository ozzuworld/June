FROM python:3.9-slim

# Install system dependencies (much simpler - no MeCab!)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Create directories
RUN mkdir -p /tmp/transformers /tmp/huggingface /cache /models && \
    chmod 777 /tmp/transformers /tmp/huggingface /cache /models

# Set environment variables
ENV TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    PYTHONPATH="/workspace"

# Install XTTS and dependencies (no version hell!)
RUN pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    pydantic-settings \
    TTS==0.21.1 \
    torch \
    torchaudio \
    soundfile \
    librosa

# Copy app
COPY . /workspace

# Test XTTS import
RUN python -c "from TTS.api import TTS; print('XTTS import: SUCCESS')"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
