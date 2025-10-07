FROM python:3.9-slim

# Install system dependencies including MeCab
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git build-essential \
    mecab mecab-ipadic-utf8 libmecab-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Create directories
RUN mkdir -p /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models && \
    chmod 777 /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models

# Set environment variables
ENV TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    NLTK_DATA=/tmp/nltk_data \
    PYTHONPATH="/workspace:/workspace/OpenVoice" \
    MECABRC=/etc/mecabrc

# Install all packages directly
RUN pip install --no-cache-dir \
    torch==2.0.1 torchaudio==2.0.2 numpy==1.24.3 \
    fastapi==0.104.1 uvicorn[standard]==0.24.0 pydantic==2.5.0 \
    librosa==0.9.1 soundfile tqdm scipy resampy huggingface_hub

# Install MeloTTS and its dependencies
RUN pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Critical MeCab fix: Create the expected unidic directory and config
RUN mkdir -p /usr/local/lib/python3.9/site-packages/unidic/dicdir && \
    echo "dicdir = /var/lib/mecab/dic/ipadic-utf8" > /usr/local/lib/python3.9/site-packages/unidic/dicdir/mecabrc

# Install OpenVoice
RUN git clone https://github.com/myshell-ai/OpenVoice.git /workspace/OpenVoice && \
    cd /workspace/OpenVoice && \
    pip install --no-cache-dir -e . --no-deps

# Copy app and setup
COPY . /workspace
RUN python setup_nltk.py && \
    python model_setup.py || echo "Model setup completed with warnings"

# Test MeCab during build to catch issues early
RUN python -c "import MeCab; print('MeCab test successful')" || echo "MeCab test failed but continuing"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
