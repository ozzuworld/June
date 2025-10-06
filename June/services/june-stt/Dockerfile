FROM python:3.9-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps that OpenVoice needs
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# CRITICAL: Pin ctranslate2 to version without execstack issue
RUN pip install --no-cache-dir ctranslate2==3.20.0

# Install faster-whisper with the compatible ctranslate2
RUN pip install --no-cache-dir faster-whisper==0.10.1

# Official OpenVoice installation method
RUN git clone https://github.com/myshell-ai/OpenVoice.git && \
    cd OpenVoice && \
    pip install -e . --no-deps

# Install MeloTTS (required for V2)
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

# Download unidic for Japanese support
RUN python -m unidic download

# Your app requirements
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy your app
COPY . /workspace

# Create Numba cache directory with proper permissions
RUN mkdir -p /workspace/numba_cache && chmod 755 /workspace/numba_cache

# Set Numba environment variables to fix caching issues
ENV NUMBA_CACHE_DIR=/workspace/numba_cache
ENV NUMBA_NUM_THREADS=1

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
