FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# CREATE DIRECTORIES WITH PROPER PERMISSIONS (this was missing!)
RUN mkdir -p /tmp/numba_cache \
             /tmp/transformers \
             /tmp/huggingface/hub \
             /tmp/torch \
             /tmp/nltk_data \
             /nltk_data \
             /cache \
             /models \
             /workspace/app && \
    chmod 777 /tmp/numba_cache \
             /tmp/transformers \
             /tmp/huggingface/hub \
             /tmp/torch \
             /tmp/nltk_data \
             /nltk_data \
             /cache \
             /models

# SET CACHE ENVIRONMENT VARIABLES (this was missing!)
ENV NUMBA_CACHE_DIR=/tmp/numba_cache \
    NUMBA_DISABLE_JIT=1 \
    NUMBA_WARNINGS=0 \
    NUMBA_DISABLE_INTEL_SVML=1 \
    TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    HUGGINGFACE_HUB_CACHE=/tmp/huggingface/hub \
    TORCH_HOME=/tmp/torch \
    NLTK_DATA=/tmp/nltk_data

# Install base dependencies first
RUN pip install --no-cache-dir \
    "torch>=2.0.0" \
    "torchaudio>=2.0.0" \
    "transformers==4.27.4" \
    "librosa==0.9.1" \
    "numpy>=1.22.0"

# Install OpenVoice
RUN git clone https://github.com/myshell-ai/OpenVoice.git /workspace/OpenVoice && \
    cd /workspace/OpenVoice && \
    pip install --no-cache-dir --no-deps -e .

# Install MeloTTS dependencies
RUN pip install --no-cache-dir \
    "mecab-python3==1.0.9" \
    "unidic-lite==1.0.8" \
    "unidic==1.1.0" \
    "pykakasi==2.2.1" \
    "fugashi==1.3.0" \
    "g2p_en==2.1.0" \
    "anyascii==0.3.2" \
    "jamo==0.4.1" \
    "g2pkk>=0.1.1" \
    "num2words==0.5.12"

# Install MeloTTS
RUN pip install --no-cache-dir --no-deps git+https://github.com/myshell-ai/MeloTTS.git

# Install remaining dependencies + your app dependencies
RUN pip install --no-cache-dir \
    "pydub==0.25.1" \
    "wavmark>=0.0.3" \
    "eng_to_ipa==0.0.2" \
    "inflect==7.0.0" \
    "unidecode==1.3.7" \
    "whisper-timestamped>=1.14.2" \
    "pypinyin==0.50.0" \
    "cn2an==0.5.22" \
    "jieba==0.42.1" \
    "gradio>=3.48.0" \
    "langid==1.1.6" \
    "cached_path" \
    "txtsplit" \
    "loguru" \
    "fastapi" \
    "uvicorn[standard]" \
    "pydantic"

# Download language models
RUN python -c "import nltk; nltk.download('averaged_perceptron_tagger')" || true
RUN python -m unidic download || true

# Copy your app
COPY . /workspace/app

# Set Python path
ENV PYTHONPATH="/workspace:/workspace/OpenVoice:${PYTHONPATH}"

WORKDIR /workspace/app
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
