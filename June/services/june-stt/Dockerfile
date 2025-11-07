FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3-pip \
    git \
    ffmpeg \
    libsndfile1 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install av + faster-whisper (latest ctranslate2 for CUDA 12 + cuDNN 9)
RUN pip install --no-cache-dir "av==12.0.0" && \
    pip install --no-cache-dir ctranslate2 huggingface-hub onnxruntime tokenizers tqdm && \
    pip install --no-cache-dir --no-deps "faster-whisper==1.0.3"

# Get whisper_streaming
RUN git clone https://github.com/ufal/whisper_streaming.git /tmp/whisper_streaming && \
    cp /tmp/whisper_streaming/whisper_online.py /app/ && \
    cp /tmp/whisper_streaming/silero_vad_iterator.py /app/ && \
    rm -rf /tmp/whisper_streaming

# App code
COPY main.py .
COPY livekit_worker.py .

EXPOSE 8000

CMD ["python3", "main.py"]