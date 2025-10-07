FROM nvidia/cuda:12.1-devel-ubuntu20.04

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set python3.11 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

WORKDIR /workspace

# Install PyTorch first (CUDA 12.1)
RUN pip3 install torch==2.4.0+cu121 torchaudio==2.4.0+cu121 --extra-index-url https://download.pytorch.org/whl/cu121

# Install F5-TTS and dependencies
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# Copy application
COPY . /workspace

# Set environment variables
ENV PYTHONPATH="/workspace"
ENV HF_HOME="/tmp/huggingface"
ENV TORCH_HOME="/tmp/torch"

# Test F5-TTS installation
RUN python3 -c "import f5_tts; print('F5-TTS successfully imported')"

EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
