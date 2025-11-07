# Use the official Fish-Speech server image as base.
# It already contains PyTorch, CUDA, and the fish-speech code. :contentReference[oaicite:5]{index=5}
FROM fishaudio/fish-speech:latest-server-cuda

WORKDIR /app

# Extra Python deps for our FastAPI microservice
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
      fastapi \
      uvicorn[standard] \
      httpx \
      python-multipart \
      pydantic \
      ormsgpack

# Copy our FastAPI app
COPY app ./app

# Copy entrypoint that runs both tools.api_server (TTS) + uvicorn
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Set defaults for model paths (can be overridden with env)
ENV LLAMA_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini \
    DECODER_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini/codec.pth \
    DECODER_CONFIG_NAME=modded_dac_vq \
    REFERENCES_DIR=/app/references \
    FISH_SPEECH_BASE_URL=http://127.0.0.1:8080 \
    FISH_SPEECH_TIMEOUT=180

EXPOSE 8000

CMD ["/app/entrypoint.sh"]
