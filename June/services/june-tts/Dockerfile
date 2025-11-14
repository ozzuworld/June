# Dockerfile for OpenAudio S1 (Fish Speech) TTS Service with GPU Support
FROM nvidia/cuda:12.6.0-cudnn-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda-12.6
ENV HF_HOME=/app/.cache/huggingface

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-dev \
    python3-pip \
    git \
    ffmpeg \
    libsndfile1 \
    libsox-dev \
    portaudio19-dev \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.12 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# Upgrade pip
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install PyTorch 2.5+ with CUDA 12.6
RUN pip3 install \
    torch==2.5.1 \
    torchvision==0.20.1 \
    torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu126

# Install core dependencies
RUN pip3 install \
    transformers>=4.36.0 \
    accelerate>=0.25.0 \
    einops>=0.7.0 \
    vector-quantize-pytorch>=1.14.0 \
    natsort>=8.4.0 \
    soundfile>=0.12.1 \
    numpy<2.0.0 \
    scipy>=1.11.4 \
    librosa>=0.10.1 \
    gradio>=4.0.0 \
    loguru>=0.7.0 \
    hydra-core>=1.3.2 \
    omegaconf>=2.3.0 \
    wandb>=0.15.0

# Install FastAPI and server dependencies
RUN pip3 install \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    httpx==0.25.0 \
    asyncpg \
    python-multipart

# Install LiveKit Python SDK
RUN pip3 install livekit==0.11.1

# Install Hugging Face CLI for model downloads
RUN pip3 install huggingface-hub[cli]

# Clone Fish Speech repository
WORKDIR /opt
RUN git clone https://github.com/fishaudio/fish-speech.git
WORKDIR /opt/fish-speech

# Install Fish Speech dependencies
RUN pip3 install -e .

# Create app directory
WORKDIR /app

# Create directories
RUN mkdir -p /app/checkpoints /app/references

# Download OpenAudio S1-mini model
RUN huggingface-cli download fishaudio/fish-speech-1.5 \
    --local-dir /app/checkpoints/fish-speech-1.5 \
    --local-dir-use-symlinks False

# Copy application code
COPY app/ /app/

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application with single worker for GPU efficiency
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]