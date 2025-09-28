# Use official Python slim image
FROM python:3.10-slim

# Set locale
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      git && \
    rm -rf /var/lib/apt/lists/*

# Install PyTorch with CUDA support (adjust CUDA version if needed)
RUN pip install --no-cache-dir \
      torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu118

# Install Hugging Face Transformers and Accelerate
RUN pip install --no-cache-dir \
      transformers accelerate

# Install OpenAI Whisper
RUN pip install --no-cache-dir openai-whisper

# Create application directory
WORKDIR /app

# Copy your transcription script or application code
# (Expect a script like transcribe.py that uses Whisper)
COPY . /app

# Default command (adjust as needed)
CMD ["python", "transcribe.py"]
