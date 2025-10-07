# Build stage
FROM python:3.9-slim as builder

# Install build dependencies INCLUDING MeCab
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential \
    mecab \
    mecab-ipadic-utf8 \
    libmecab-dev && \
    rm -rf /var/lib/apt/lists/*

# Install packages to user directory
ENV PIP_USER=1
ENV PATH="/root/.local/bin:$PATH"

# Install core ML packages
RUN pip install --no-cache-dir --user \
    torch==2.0.1 torchaudio==2.0.2 \
    numpy==1.24.3 \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    librosa==0.9.1 \
    soundfile \
    tqdm \
    scipy \
    resampy \
    huggingface_hub

# Install MeloTTS
RUN pip install --no-cache-dir --user git+https://github.com/myshell-ai/MeloTTS.git

# Clone and install OpenVoice
RUN git clone https://github.com/myshell-ai/OpenVoice.git /tmp/OpenVoice && \
    cd /tmp/OpenVoice && \
    pip install --user -e . --no-deps

# Production stage
FROM python:3.9-slim

# Install runtime dependencies INCLUDING MeCab
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    mecab \
    mecab-ipadic-utf8 && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy OpenVoice source
COPY --from=builder /tmp/OpenVoice /workspace/OpenVoice

# Create directories and set permissions
RUN mkdir -p /workspace /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models && \
    chmod 777 /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models

# Set environment variables
ENV PATH="/root/.local/bin:$PATH" \
    TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    NLTK_DATA=/tmp/nltk_data \
    PYTHONPATH="/workspace:/workspace/OpenVoice:${PYTHONPATH}" \
    MECABRC=/etc/mecabrc

WORKDIR /workspace

# Copy your app
COPY . /workspace

# Setup NLTK and models during build
RUN python setup_nltk.py && \
    python model_setup.py || echo "Model setup completed with warnings"

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
