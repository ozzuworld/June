FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git ca-certificates libsox-dev build-essential cmake \
    libasound-dev portaudio19-dev libportaudio2 libportaudiocpp0 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/fishaudio/fish-speech.git /app/fish-speech

WORKDIR /app/fish-speech
RUN pip install --no-cache-dir --upgrade pip && \
    pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu118 && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir uvicorn fastapi httpx ormsgpack pydantic

WORKDIR /app
RUN mkdir -p /app/checkpoints /app/references

COPY app/ /app/app/

ENV LLAMA_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini \
    DECODER_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini/codec.pth \
    DECODER_CONFIG_NAME=modded_dac_vq \
    REFERENCES_DIR=/app/references \
    COMPILE=1 \
    FISH_SPEECH_BASE_URL=http://127.0.0.1:8080

EXPOSE 8000 8080

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

CMD /app/entrypoint.sh & sleep 30 && uvicorn app.main:app --host 0.0.0.0 --port 8000
