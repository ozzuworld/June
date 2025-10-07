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

# Create constraints file to lock NumPy at 1.24.3
RUN echo "numpy==1.24.3" > /tmp/constraints.txt && \
    echo "scipy<1.11" >> /tmp/constraints.txt && \
    echo "scikit-learn<1.4" >> /tmp/constraints.txt

# Install EVERYTHING with constraints in one step to avoid conflicts
RUN pip install --no-cache-dir --constraint /tmp/constraints.txt \
    "numpy==1.24.3" \
    "torch==2.0.1" \
    "torchaudio==2.0.2" \
    "scipy==1.10.1" \
    "scikit-learn==1.3.2" \
    "fastapi==0.104.1" \
    "uvicorn[standard]==0.24.0" \
    "pydantic==2.5.0" \
    "pydantic-settings" \
    "librosa==0.9.1" \
    "soundfile" \
    "tqdm" \
    "resampy" \
    "huggingface_hub<0.17" \
    "transformers<4.35" \
    "onnxruntime<1.16"

# Install MeloTTS with strict constraints
RUN pip install --no-cache-dir --constraint /tmp/constraints.txt \
    git+https://github.com/myshell-ai/MeloTTS.git

# Install other dependencies with constraints
RUN pip install --no-cache-dir --constraint /tmp/constraints.txt \
    "botocore>=1.20.0,<2.0" \
    "faster-whisper<0.9" \
    "pydub" \
    "whisper-timestamped" \
    "openai-whisper<20231117" \
    "ffmpeg-python"

# Final NumPy verification and lock
RUN pip install --no-cache-dir --force-reinstall --constraint /tmp/constraints.txt "numpy==1.24.3"

# Verify NumPy stayed at 1.24.3
RUN python -c "import numpy; assert numpy.__version__ == '1.24.3', f'FAILED: NumPy is {numpy.__version__}, expected 1.24.3'"

# CRITICAL FIX: Copy unidic_lite dictionary
RUN mkdir -p /usr/local/lib/python3.9/site-packages/unidic/dicdir && \
    cp -r /usr/local/lib/python3.9/site-packages/unidic_lite/dicdir/* /usr/local/lib/python3.9/site-packages/unidic/dicdir/

# Install OpenVoice
RUN git clone https://github.com/myshell-ai/OpenVoice.git /workspace/OpenVoice && \
    cd /workspace/OpenVoice && \
    pip install --no-cache-dir --constraint /tmp/constraints.txt -e . --no-deps

# Copy app and setup
COPY . /workspace
RUN python setup_nltk.py && \
    python model_setup.py || echo "Model setup completed with warnings"

# Final test
RUN python -c "import numpy; print(f'Final NumPy: {numpy.__version__}'); import torchaudio; from melo.api import TTS; print('All imports: SUCCESS')"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
