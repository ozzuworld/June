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

# Install ONLY essential packages (no complex ML ecosystem)
RUN pip install --no-cache-dir \
    torch==2.0.1 torchaudio==2.0.2 \
    numpy==1.24.3 \
    tqdm \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0

# Install OpenVoice with no deps
RUN git clone https://github.com/myshell-ai/OpenVoice.git /workspace/OpenVoice && \
    cd /workspace/OpenVoice && \
    pip install --no-cache-dir -e . --no-deps

# Install only essential MeloTTS deps
RUN pip install --no-cache-dir \
    unidic-lite==1.0.8 \
    && pip install --no-cache-dir --no-deps git+https://github.com/myshell-ai/MeloTTS.git

# Copy your app
COPY . /workspace

WORKDIR /workspace
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
