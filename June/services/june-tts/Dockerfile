# Base: official Fish-Speech server image (has code + deps)
FROM fishaudio/fish-speech:latest-server-cuda

WORKDIR /app

# Install extra deps for API + model download
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
      fastapi \
      uvicorn[standard] \
      httpx \
      python-multipart \
      pydantic \
      ormsgpack \
      huggingface_hub

# Download model checkpoint into the image at build time
RUN mkdir -p /app/checkpoints && \
    python - <<'PY'
from huggingface_hub import snapshot_download

print("Downloading OpenAudio S1 mini checkpoint into /app/checkpoints/openaudio-s1-mini ...")
snapshot_download(
    repo_id="fishaudio/openaudio-s1-mini",
    local_dir="/app/checkpoints/openaudio-s1-mini",
    local_dir_use_symlinks=False,
)
print("Download complete.")
PY

# References directory for voice cloning (can still be mounted from host if you want)
RUN mkdir -p /app/references

# Copy FastAPI app + entrypoint
COPY app ./app
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Default env for internal paths
ENV LLAMA_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini \
    DECODER_CHECKPOINT_PATH=/app/checkpoints/openaudio-s1-mini/codec.pth \
    DECODER_CONFIG_NAME=modded_dac_vq \
    REFERENCES_DIR=/app/references \
    FISH_SPEECH_BASE_URL=http://127.0.0.1:8080 \
    FISH_SPEECH_TIMEOUT=180 \
    COMPILE=1

EXPOSE 8000

CMD ["/app/entrypoint.sh"]
