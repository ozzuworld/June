FROM python:3.9-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps that OpenVoice needs
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Create ALL necessary directories with proper permissions (including system ones)
RUN mkdir -p /tmp/numba_cache \
             /tmp/transformers \
             /tmp/huggingface/hub \
             /tmp/torch \
             /tmp/nltk_data \
             /nltk_data \
             /cache \
             /models && \
    chmod 777 /tmp/numba_cache \
             /tmp/transformers \
             /tmp/huggingface/hub \
             /tmp/torch \
             /tmp/nltk_data \
             /nltk_data \
             /cache \
             /models

# Set environment variables for all caching systems
ENV NUMBA_CACHE_DIR=/tmp/numba_cache
ENV NUMBA_DISABLE_JIT=0
ENV NUMBA_WARNINGS=0
ENV TRANSFORMERS_CACHE=/tmp/transformers
ENV HF_HOME=/tmp/huggingface
ENV HUGGINGFACE_HUB_CACHE=/tmp/huggingface/hub
ENV TORCH_HOME=/tmp/torch
ENV NLTK_DATA=/tmp/nltk_data

# CRITICAL: Pin ctranslate2 to version without execstack issue
RUN pip install --no-cache-dir ctranslate2==3.20.0

# Install faster-whisper with the compatible ctranslate2
RUN pip install --no-cache-dir faster-whisper==0.10.1

# Fix dependency version conflicts BEFORE installing MeloTTS
RUN pip install --no-cache-dir \
    "botocore>=1.29.0,<1.35.0" \
    "boto3>=1.26.0,<1.35.0" \
    "cached-path>=1.5.0"

# Official OpenVoice installation method
RUN git clone https://github.com/myshell-ai/OpenVoice.git && \
    cd OpenVoice && \
    pip install -e . --no-deps

# Install MeloTTS (required for V2) - now with fixed dependencies
RUN pip install git+https://github.com/myshell-ai/MeloTTS.git

# Install remaining OpenVoice dependencies manually (to avoid version conflicts)
RUN pip install --no-cache-dir \
    librosa>=0.8.1 \
    wavmark>=0.0.3 \
    pydub>=0.25.1 \
    whisper-timestamped>=1.14.2 \
    tqdm \
    inflect>=7.0.0 \
    unidecode>=1.3.7 \
    eng_to_ipa>=0.0.2 \
    pypinyin>=0.50.0 \
    cn2an>=0.5.22 \
    jieba>=0.42.1 \
    langid>=1.1.6

# Pre-download NLTK data to avoid runtime downloads (to both locations)
RUN python -c "import nltk; nltk.download('averaged_perceptron_tagger', download_dir='/tmp/nltk_data'); nltk.download('cmudict', download_dir='/tmp/nltk_data'); nltk.download('averaged_perceptron_tagger', download_dir='/nltk_data'); nltk.download('cmudict', download_dir='/nltk_data')"

# Download unidic for Japanese support
RUN python -m unidic download

# Your app requirements
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy your app
COPY . /workspace

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
