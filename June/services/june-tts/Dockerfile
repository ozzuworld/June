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

# Download pretrained models (CosyVoice2-0.5B recommended)
RUN pip install --no-cache-dir modelscope && \
    python -c "from modelscope import snapshot_download; \
    snapshot_download('iic/CosyVoice2-0.5B', local_dir='pretrained_models/CosyVoice2-0.5B'); \
    snapshot_download('iic/CosyVoice-ttsfrd', local_dir='pretrained_models/CosyVoice-ttsfrd')"

# Download spk2info.pt for SFT speaker support (英文女, 中文女, etc.)
# CosyVoice2-0.5B does not include spk2info.pt by default, so we get it from CosyVoice-300M-SFT
RUN python3 << 'PYTHON_SCRIPT'
from modelscope import snapshot_download
import shutil
import os

print("=" * 80)
print("📥 Downloading spk2info.pt for SFT speaker support...")
print("=" * 80)

try:
    # Download CosyVoice-300M-SFT to get spk2info.pt
    sft_dir = snapshot_download('iic/CosyVoice-300M-SFT', local_dir='/tmp/cosyvoice-sft')
    src = os.path.join(sft_dir, 'spk2info.pt')
    dst = 'pretrained_models/CosyVoice2-0.5B/spk2info.pt'
    
    if os.path.exists(src):
        shutil.copy(src, dst)
        file_size_mb = os.path.getsize(dst) / 1024 / 1024
        print(f"✅ Successfully copied spk2info.pt to {dst}")
        print(f"   File size: {file_size_mb:.2f} MB")
        print("   This enables SFT mode with predefined speakers:")
        print("   - 中文女 (Chinese Female)")
        print("   - 中文男 (Chinese Male)")
        print("   - 英文女 (English Female)")
        print("   - 英文男 (English Male)")
        print("   - 日语男 (Japanese Male)")
        print("   - 粤语女 (Cantonese Female)")
        print("   - 韩语女 (Korean Female)")
    else:
        print(f"❌ ERROR: spk2info.pt not found at {src}")
        print("   SFT mode will not work without this file!")
        exit(1)
    
    # Clean up temporary download
    if os.path.exists('/tmp/cosyvoice-sft'):
        shutil.rmtree('/tmp/cosyvoice-sft')
        print("🧹 Cleaned up temporary files")
    
    print("=" * 80)
    print("✅ spk2info.pt setup complete")
    print("=" * 80)
    
except Exception as e:
    print(f"❌ ERROR during spk2info.pt setup: {e}")
    exit(1)

PYTHON_SCRIPT

# Optional: Install ttsfrd for better text normalization
RUN cd pretrained_models/CosyVoice-ttsfrd/ && \
    unzip -o resource.zip -d . && \
    pip install --no-cache-dir ttsfrd_dependency-0.1-py3-none-any.whl && \
    pip install --no-cache-dir ttsfrd-0.4.2-cp310-cp310-linux_x86_64.whl || true

# Copy application files
COPY main.py /opt/CosyVoice/main.py
COPY livekit_publisher.py /opt/CosyVoice/livekit_publisher.py

# Create necessary directories
RUN mkdir -p /opt/CosyVoice/logs /opt/CosyVoice/cache

# Expose port for API
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Set the entrypoint
CMD ["python", "main.py", "--port", "8000", "--host", "0.0.0.0", "--model_dir", "pretrained_models/CosyVoice2-0.5B"]