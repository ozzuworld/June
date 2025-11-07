# Dockerfile

# Base: Fish-Speech server image (CUDA + code + tools/api_server.py)
FROM fishaudio/fish-speech:server-cuda-nightly

WORKDIR /app

# Install extra deps for API + runtime model download
RUN pip install --no-cache-dir --break-system-packages --upgrade pip && \
    pip install --no-cache-dir --break-system-packages \
      fastapi \
      uvicorn[standard] \
      httpx \
      python-multipart \
      pydantic \
      ormsgpack \
      huggingface_hub \
      pyrootutils \
      kui \
      loguru

# Prepare directories; the actual model will be downloaded at runtime
RUN mkdir -p /app/checkpoints /app/references

# Copy FastAPI app + entrypoint into the image
COPY app ./app
COPY entrypoint.sh /app/entrypoint.sh

# Default env paths for the internal Fish-Speech API server
ENV LLAMA_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini \
    DECODER_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini/codec.pth \
    DECODER_CONFIG_NAME=modded_dac_vq \
    REFERENCES_DIR=/app/references \
    FISH_SPEECH_BASE_URL=http://127.0.0.1:8080 \
    FISH_SPEECH_TIMEOUT=180 \
    COMPILE=1

EXPOSE 8000

# Remove base image entrypoint and run our script instead
ENTRYPOINT []
CMD ["bash", "/app/entrypoint.sh"]
