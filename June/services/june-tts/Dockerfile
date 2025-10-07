# Multi-stage build for better optimization
FROM python:3.9-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies in builder stage
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --user \
    torch==2.0.1 torchaudio==2.0.2 \
    numpy==1.24.3 \
    tqdm soundfile librosa==0.9.1 \
    fastapi==0.104.1 uvicorn[standard]==0.24.0 pydantic==2.5.0 \
    huggingface_hub nltk mecab-python3 pynini \
    pypinyin jieba g2p_en num2words inflect \
    unidic-lite==1.0.8

# Clone and install OpenVoice
RUN git clone https://github.com/myshell-ai/OpenVoice.git /tmp/OpenVoice && \
    cd /tmp/OpenVoice && \
    pip install --user -e . --no-deps

# Install MeloTTS
RUN pip install --user --no-deps git+https://github.com/myshell-ai/MeloTTS.git

# Production stage
FROM python:3.9-slim

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local

# Create directories and set permissions
RUN mkdir -p /workspace /tmp/transformers /tmp/huggingface /tmp/nltk_data \
             /cache /models /models/openvoice/checkpoints_v2 && \
    chmod -R 777 /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models

# Set environment variables
ENV PATH=/root/.local/bin:$PATH \
    PYTHONPATH="/workspace:/workspace/OpenVoice:${PYTHONPATH}" \
    TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    NLTK_DATA=/tmp/nltk_data \
    OPENVOICE_CHECKPOINTS_V2=/models/openvoice/checkpoints_v2

WORKDIR /workspace

# Copy application code
COPY . /workspace

# Copy OpenVoice from builder
COPY --from=builder /tmp/OpenVoice /workspace/OpenVoice

# Setup NLTK and models during build
RUN python setup_nltk.py && \
    python model_setup.py || echo "Model setup completed with warnings"

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
