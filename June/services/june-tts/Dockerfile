# Multi-stage build to reduce final image size
FROM python:3.9-slim as builder

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    aria2 \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies in builder stage
RUN pip install --no-cache-dir --upgrade pip

# Install core dependencies first (most stable)
RUN pip install --no-cache-dir \
    "botocore>=1.29.0,<1.35.0" \
    "boto3>=1.26.0,<1.35.0" \
    "cached-path>=1.5.0" \
    "ctranslate2==3.20.0" \
    "faster-whisper==0.10.1"

# Clone and install OpenVoice (lightweight approach)
RUN git clone https://github.com/myshell-ai/OpenVoice.git /tmp/OpenVoice && \
    cd /tmp/OpenVoice && \
    pip install --no-cache-dir -e . --no-deps

# Install MeloTTS separately
RUN pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Install remaining dependencies in one go
RUN pip install --no-cache-dir \
    librosa>=0.8.1 \
    wavmark>=0.0.3 \
    pydub>=0.25.1 \
    whisper-timestamped>=1.14.2 \
    inflect>=7.0.0 \
    unidecode>=1.3.7 \
    eng_to_ipa>=0.0.2 \
    pypinyin>=0.50.0 \
    cn2an>=0.5.22 \
    jieba>=0.42.1 \
    langid>=1.1.6 \
    soundfile \
    gradio==3.50.2

# Download models in builder stage (but don't include in final image)
WORKDIR /tmp/models

# Pre-download NLTK data
RUN python -c "import nltk; nltk.download('averaged_perceptron_tagger'); nltk.download('cmudict')" || true

# Download unidic for Japanese
RUN python -m unidic download || true

# === FINAL STAGE ===
FROM python:3.9-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create directories with proper permissions
RUN mkdir -p /tmp/numba_cache \
             /tmp/transformers \
             /tmp/huggingface/hub \
             /tmp/torch \
             /tmp/nltk_data \
             /nltk_data \
             /cache \
             /models \
             /workspace && \
    chmod 777 /tmp/numba_cache \
             /tmp/transformers \
             /tmp/huggingface/hub \
             /tmp/torch \
             /tmp/nltk_data \
             /nltk_data \
             /cache \
             /models

# Set environment variables for caching
ENV NUMBA_CACHE_DIR=/tmp/numba_cache \
    NUMBA_DISABLE_JIT=1 \
    NUMBA_WARNINGS=0 \
    TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    HUGGINGFACE_HUB_CACHE=/tmp/huggingface/hub \
    TORCH_HOME=/tmp/torch \
    NLTK_DATA=/tmp/nltk_data

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy OpenVoice source
COPY --from=builder /tmp/OpenVoice /workspace/OpenVoice

# Copy NLTK data
COPY --from=builder /root/nltk_data /tmp/nltk_data/
COPY --from=builder /root/nltk_data /nltk_data/

WORKDIR /workspace

# Copy your application code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your app
COPY . .

EXPOSE 8080

# Use exec form for better signal handling
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
