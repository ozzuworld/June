# Dockerfile for OpenAudio S1 (Fish Speech) TTS Service with GPU Support
FROM nvidia/cuda:12.6.0-cudnn-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda-12.6
ENV HF_HOME=/app/.cache/huggingface

# Install system dependencies and add deadsnakes PPA for Python 3.12
RUN apt-get update && apt-get install -y \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update \
    && apt-get install -y \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    build-essential \
    gcc \
    g++ \
    git \
    ffmpeg \
    libsndfile1 \
    libsox-dev \
    portaudio19-dev \
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.12 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# Install pip for Python 3.12
RUN curl -sS https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3.12 get-pip.py && \
    rm get-pip.py && \
    python3.12 -m pip install --upgrade pip setuptools wheel

# Install PyTorch 2.6.0 with CUDA 12.6 (earliest version with cu126 support)
RUN python3.12 -m pip install \
    torch==2.6.0+cu126 \
    torchvision==0.21.0+cu126 \
    torchaudio==2.6.0+cu126 \
    --index-url https://download.pytorch.org/whl/cu126

# Install core dependencies
RUN python3.12 -m pip install \
    transformers>=4.36.0 \
    accelerate>=0.25.0 \
    einops>=0.7.0 \
    vector-quantize-pytorch>=1.14.0 \
    natsort>=8.4.0 \
    soundfile>=0.12.1 \
    "numpy<2.0.0" \
    scipy>=1.11.4 \
    librosa>=0.10.1 \
    gradio>=4.0.0 \
    loguru>=0.7.0 \
    hydra-core>=1.3.2 \
    omegaconf>=2.3.0 \
    wandb>=0.15.0

# Install FastAPI and server dependencies
RUN python3.12 -m pip install \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    httpx==0.25.0 \
    asyncpg \
    python-multipart

# Install LiveKit Python SDK with compatible protobuf
RUN python3.12 -m pip install "protobuf>=4.21.0,<5.0.0" livekit==0.11.1

# Install Hugging Face CLI for model downloads
RUN python3.12 -m pip install huggingface-hub[cli]

# Clone Fish Speech repository
WORKDIR /opt
RUN git clone https://github.com/fishaudio/fish-speech.git
WORKDIR /opt/fish-speech

# Install Fish Speech dependencies
RUN python3.12 -m pip install -e .

# Force reinstall protobuf 4.x and livekit (Fish Speech may have upgraded protobuf to 5.x)
RUN python3.12 -m pip install --force-reinstall --no-deps "protobuf>=4.21.0,<5.0.0"
RUN python3.12 -m pip install --no-deps livekit==0.11.1

# Create app directory
WORKDIR /app

# Copy application code
COPY app/ /app/

# Create directories (models will be downloaded at runtime)
RUN mkdir -p /app/checkpoints /app/references

# Make start script executable
RUN chmod +x /app/start.sh

# Expose ports (8000 for our API, 9880 for Fish Speech internal API)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=240s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run via start script (starts Fish Speech API + our wrapper)
CMD ["/app/start.sh"]