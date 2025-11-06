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

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Download pretrained models (CosyVoice2-0.5B recommended)
RUN pip install --no-cache-dir modelscope && \
    python -c "from modelscope import snapshot_download; \
    snapshot_download('iic/CosyVoice2-0.5B', local_dir='pretrained_models/CosyVoice2-0.5B'); \
    snapshot_download('iic/CosyVoice-ttsfrd', local_dir='pretrained_models/CosyVoice-ttsfrd')"

# Optional: Install ttsfrd for better text normalization
RUN cd pretrained_models/CosyVoice-ttsfrd/ && \
    unzip -o resource.zip -d . && \
    pip install --no-cache-dir ttsfrd_dependency-0.1-py3-none-any.whl && \
    pip install --no-cache-dir ttsfrd-0.4.2-cp310-cp310-linux_x86_64.whl || true

# Expose port for web UI
EXPOSE 50000

# Set the entrypoint
CMD ["python", "webui.py", "--port", "50000", "--model_dir", "pretrained_models/CosyVoice2-0.5B"]