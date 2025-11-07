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

# Install base Python dependencies (everything EXCEPT faster-whisper)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ---------- FAST-WHISPER + AV FIX ----------
# 1) Install an av version that HAS a prebuilt wheel for cp310 on manylinux
#    -> no compiling, no FFmpeg headers needed.
# 2) Install faster-whisper WITHOUT its dependencies (`--no-deps`)
#    so it doesn't try to pull av==11.* and re-break everything.
RUN pip install --no-cache-dir "av==12.0.0" ctranslate2 huggingface-hub onnxruntime tokenizers tqdm && \
    pip install --no-cache-dir --no-deps "faster-whisper==1.0.3"
# -------------------------------------------

# Clone whisper_streaming and copy whisper_online.py
RUN git clone https://github.com/ufal/whisper_streaming.git /tmp/whisper_streaming && \
    cp /tmp/whisper_streaming/whisper_online.py /app/ && \
    rm -rf /tmp/whisper_streaming

# Copy service code
COPY main.py .

EXPOSE 8000

CMD ["python", "main.py"]
