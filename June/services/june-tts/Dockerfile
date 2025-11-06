FROM nvidia/cuda:12.1.0-cudnn8-devel-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    git-lfs \
    wget \
    curl \
    sox \
    libsox-dev \
    build-essential \
    python3.10 \
    python3.10-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Set python3.10 as default python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

# Upgrade pip
RUN python -m pip install --upgrade pip

# Set working directory
WORKDIR /opt/CosyVoice

# Clone the repository with submodules
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git . && \
    git submodule update --init --recursive

# Install CosyVoice Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install additional dependencies for our service
RUN pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    python-multipart==0.0.6 \
    pydantic==2.5.0 \
    livekit==0.11.1 \
    httpx==0.27.2

# Download pretrained models (CosyVoice2-0.5B)
RUN pip install --no-cache-dir modelscope && \
    python -c "from modelscope import snapshot_download; \
    snapshot_download('iic/CosyVoice2-0.5B', local_dir='pretrained_models/CosyVoice2-0.5B'); \
    snapshot_download('iic/CosyVoice-ttsfrd', local_dir='pretrained_models/CosyVoice-ttsfrd')"

# NOTE: CosyVoice2 does NOT support SFT mode with predefined speakers
# The spk2info.pt file from CosyVoice-300M-SFT is NOT compatible with CosyVoice2
# CosyVoice2 uses zero-shot, cross-lingual, and instruct2 methods instead

# Optional: Install ttsfrd for better text normalization
RUN cd pretrained_models/CosyVoice-ttsfrd/ && \
    unzip -o resource.zip -d . && \
    pip install --no-cache-dir ttsfrd_dependency-0.1-py3-none-any.whl && \
    pip install --no-cache-dir ttsfrd-0.4.2-cp310-cp310-linux_x86_64.whl || true

# Copy application files
COPY main.py /opt/CosyVoice/main.py
COPY livekit_publisher.py /opt/CosyVoice/livekit_publisher.py

# Create necessary directories
RUN mkdir -p /opt/CosyVoice/logs /opt/CosyVoice/cache /opt/CosyVoice/asset

# Download reference audio files for zero-shot synthesis
# These are required for CosyVoice2 voice cloning
RUN cd /opt/CosyVoice && \
    wget -q -O asset/zero_shot_prompt.wav \
    https://github.com/FunAudioLLM/CosyVoice/raw/main/asset/zero_shot_prompt.wav || \
    echo "Warning: Could not download reference audio. Manual setup required."

RUN cd /opt/CosyVoice && \
    wget -q -O asset/cross_lingual_prompt.wav \
    https://github.com/FunAudioLLM/CosyVoice/raw/main/asset/cross_lingual_prompt.wav || \
    echo "Warning: Could not download reference audio. Manual setup required."

# Expose port for API
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Set the entrypoint
CMD ["python", "main.py", "--port", "8000", "--host", "0.0.0.0", "--model_dir", "pretrained_models/CosyVoice2-0.5B"]
