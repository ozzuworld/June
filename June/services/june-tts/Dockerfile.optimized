# Optimized Dockerfile for June TTS with Chatterbox optimizations
FROM pytorch/pytorch:2.4.0-cuda12.4-cudnn9-devel

# Set environment variables for optimization
ENV PYTHONUNBUFFERED=1
ENV TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"
ENV CUDA_VISIBLE_DEVICES=0
ENV TORCH_COMPILE_DEBUG=0
ENV PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"

# Install system dependencies optimized for performance
RUN apt-get update && apt-get install -y \
    git \
    wget \
    curl \
    ffmpeg \
    libsndfile1 \
    libasound2-dev \
    portaudio19-dev \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .

# Install optimized Python packages
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir torch==2.4.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu124
RUN pip install --no-cache-dir -r requirements.txt

# Install performance optimization packages
RUN pip install --no-cache-dir \
    triton>=2.3.0 \
    flash-attn \
    xformers \
    ninja

# Copy application code
COPY . .

# Create directories for caching and temporary files
RUN mkdir -p /app/cache /app/temp
ENV TRANSFORMERS_CACHE=/app/cache
ENV HF_HOME=/app/cache
ENV TORCH_HOME=/app/cache

# Expose port
EXPOSE 8000

# Health check with optimization status
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

# Run optimized service
CMD ["python", "main_optimized.py"]
