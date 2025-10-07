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

# Install core packages
RUN pip install --no-cache-dir \
    torch==2.0.1 torchaudio==2.0.2 numpy==1.24.3 \
    fastapi==0.104.1 uvicorn[standard]==0.24.0 pydantic==2.5.0 \
    librosa==0.9.1 soundfile tqdm scipy resampy huggingface_hub

# Install MeloTTS
RUN pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Fix botocore version incompatibility 
RUN pip install --no-cache-dir --upgrade botocore>=1.20.0

# Install ALL OpenVoice dependencies that were skipped by --no-deps
RUN pip install --no-cache-dir \
    faster-whisper \
    onnxruntime \
    pydub \
    whisper-timestamped \
    openai-whisper \
    ffmpeg-python

# CRITICAL FIX: Copy unidic_lite dictionary to the expected unidic location
RUN mkdir -p /usr/local/lib/python3.9/site-packages/unidic/dicdir && \
    cp -r /usr/local/lib/python3.9/site-packages/unidic_lite/dicdir/* /usr/local/lib/python3.9/site-packages/unidic/dicdir/

# Test MeCab works
RUN python -c "import MeCab; tagger = MeCab.Tagger(); print('MeCab configuration successful')"

# Test MeloTTS import
RUN python -c "from melo.api import TTS as MeloTTS; print('MeloTTS import successful')"

# Install OpenVoice with --no-deps (but dependencies installed above)
RUN git clone https://github.com/myshell-ai/OpenVoice.git /workspace/OpenVoice && \
    cd /workspace/OpenVoice && \
    pip install --no-cache-dir -e . --no-deps

# Test OpenVoice import
RUN python -c "from openvoice import se_extractor; print('OpenVoice import successful')"

# Copy app and setup
COPY . /workspace
RUN python setup_nltk.py && \
    python model_setup.py || echo "Model setup completed with warnings"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
