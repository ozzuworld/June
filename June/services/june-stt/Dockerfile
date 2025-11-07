FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    libsndfile1 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (everything *except* faster-whisper + av)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install av using a wheel + faster-whisper without pulling its deps again
RUN pip install --no-cache-dir "av==12.0.0" ctranslate2 huggingface-hub onnxruntime tokenizers tqdm && \
    pip install --no-cache-dir --no-deps "faster-whisper==1.0.3"

# Get whisper_streaming helper (BOTH files: whisper_online + silero_vad_iterator)
RUN git clone https://github.com/ufal/whisper_streaming.git /tmp/whisper_streaming && \
    cp /tmp/whisper_streaming/whisper_online.py /app/ && \
    cp /tmp/whisper_streaming/silero_vad_iterator.py /app/ && \
    rm -rf /tmp/whisper_streaming

# App code
COPY main.py .
COPY livekit_worker.py .

EXPOSE 8000

CMD ["python", "main.py"]
