FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Create cache directories with proper permissions
RUN mkdir -p /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models && \
    chmod 777 /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models

# Set environment variables
ENV TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    NLTK_DATA=/tmp/nltk_data \
    PYTHONPATH="/workspace:/workspace/OpenVoice:${PYTHONPATH}"

# Install core ML packages first (most important versions)
RUN pip install --no-cache-dir \
    torch==2.0.1 torchaudio==2.0.2 \
    numpy==1.24.3

# Install core web framework
RUN pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0

# Install audio processing
RUN pip install --no-cache-dir \
    librosa==0.9.1 \
    soundfile \
    tqdm \
    scipy \
    resampy

# Install model management
RUN pip install --no-cache-dir \
    huggingface_hub

# Install MeloTTS with ALL its dependencies (remove --no-deps)
RUN pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Install OpenVoice with --no-deps (this one we keep controlled)
RUN git clone https://github.com/myshell-ai/OpenVoice.git /workspace/OpenVoice && \
    cd /workspace/OpenVoice && \
    pip install --no-cache-dir -e . --no-deps

# Copy your app
COPY . /workspace

# Setup NLTK and models during build
RUN python setup_nltk.py && \
    python model_setup.py || echo "Model setup completed with warnings"

WORKDIR /workspace
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
