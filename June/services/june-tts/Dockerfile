# Build from scratch - no base image available
FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    libsox-dev \
    build-essential \
    cmake \
    libasound-dev \
    portaudio19-dev \
    libportaudio2 \
    libportaudiocpp0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Clone fish-speech
RUN git clone https://github.com/fishaudio/fish-speech.git /app/fish-speech

# Install fish-speech deps
WORKDIR /app/fish-speech
RUN pip install --no-cache-dir --break-system-packages --upgrade pip && \
    pip install --no-cache-dir --break-system-packages -e .

# Copy your wrapper code
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /app/requirements.txt

COPY app /app/app
COPY entrypoint.sh /app/entrypoint.sh

RUN mkdir -p /app/checkpoints /app/references

# Set fish-speech in PATH  
ENV PATH="/app/fish-speech:${PATH}" \
    PYTHONPATH="/app/fish-speech:${PYTHONPATH}" \
    LLAMA_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini \
    DECODER_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini/codec.pth \
    DECODER_CONFIG_NAME=modded_dac_vq \
    REFERENCES_DIR=/app/references \
    FISH_SPEECH_BASE_URL=http://127.0.0.1:8080 \
    FISH_SPEECH_TIMEOUT=180 \
    COMPILE=1

WORKDIR /app

EXPOSE 8000

CMD ["bash", "/app/entrypoint.sh"]