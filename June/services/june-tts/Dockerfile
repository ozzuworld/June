FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Create cache directories
RUN mkdir -p /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models && \
    chmod 777 /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models

# Set environment variables
ENV TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    NLTK_DATA=/tmp/nltk_data

# Install ONLY essential packages (avoid gradio dependency hell)
RUN pip install --no-cache-dir \
    torch torchaudio \
    librosa==0.9.1 \
    numpy \
    fastapi \
    uvicorn[standard]

# Install OpenVoice
RUN git clone https://github.com/myshell-ai/OpenVoice.git . && \
    pip install --no-cache-dir -e . --no-deps

# Install MeloTTS core only (skip heavy dependencies)
RUN pip install --no-cache-dir \
    mecab-python3 unidic-lite pykakasi \
    && pip install --no-cache-dir --no-deps git+https://github.com/myshell-ai/MeloTTS.git

# Copy your app
COPY . /workspace/app

ENV PYTHONPATH="/workspace:${PYTHONPATH}"
WORKDIR /workspace/app

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
