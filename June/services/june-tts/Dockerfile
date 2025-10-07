FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Create cache directories with proper permissions
RUN mkdir -p /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models && \
    chmod 777 /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models

# Set environment variables for caching
ENV TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    NLTK_DATA=/tmp/nltk_data \
    PYTHONPATH="/workspace:${PYTHONPATH}"

# Install core ML dependencies INCLUDING NLTK
RUN pip install --no-cache-dir \
    torch torchaudio \
    librosa==0.9.1 \
    numpy \
    nltk \
    fastapi \
    uvicorn[standard] \
    pydantic

# Download NLTK data (this will work now since NLTK is installed)
RUN python -c "import nltk; nltk.download('averaged_perceptron_tagger', download_dir='/tmp/nltk_data'); nltk.download('punkt', download_dir='/tmp/nltk_data'); nltk.download('cmudict', download_dir='/tmp/nltk_data')" || true

# Install OpenVoice
RUN git clone https://github.com/myshell-ai/OpenVoice.git /workspace/OpenVoice && \
    cd /workspace/OpenVoice && \
    pip install --no-cache-dir -e . --no-deps

# Install MeloTTS dependencies
RUN pip install --no-cache-dir \
    mecab-python3 unidic-lite pykakasi \
    && pip install --no-cache-dir --no-deps git+https://github.com/myshell-ai/MeloTTS.git

# Copy your app to the workspace root
COPY . /workspace

# Set working directory to workspace root where your files are
WORKDIR /workspace

EXPOSE 8080

# Start uvicorn with the correct module path
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
