FROM nvidia/cuda:12.2.0-cudnn8-runtime-ubuntu22.04

# Install build tools and Python
RUN apt-get update && \
    apt-get install -y git python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Clone fish-speech and install dependencies
RUN git clone --depth=1 https://github.com/fishaudio/fish-speech.git /opt/fish-speech
WORKDIR /opt/fish-speech
RUN pip install -r requirements.txt && \
    pip install -e .

# Copy your FastAPI wrapper if needed (optional)
COPY main.py /app/main.py

# Default command: launch Fish-Speech’s own API server
# Expects checkpoints and reference audio mounted into /app/checkpoints and /app/references
ENV API_SERVER_PORT=8080 API_SERVER_NAME=june-tts-fish
CMD python -m tools.api_server --listen 0.0.0.0:$API_SERVER_PORT \
    --llama-checkpoint-path /app/checkpoints/llama \
    --vq-path /app/checkpoints/vqgan \
    --codec-checkpoint-path /app/checkpoints/codec \
    --reference-sample-path /app/references
