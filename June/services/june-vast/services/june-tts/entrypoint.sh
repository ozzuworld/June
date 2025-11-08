#!/usr/bin/env bash
set -euo pipefail

: "${LLAMA_CHECKPOINT_PATH:=/app/checkpoints/openaudio-s1-mini}"
: "${DECODER_CHECKPOINT_PATH:=/app/checkpoints/openaudio-s1-mini/codec.pth}"
: "${DECODER_CONFIG_NAME:=modded_dac_vq}"
: "${API_SERVER_HOST:=0.0.0.0}"
: "${API_SERVER_PORT:=8080}"

echo "[entrypoint] Checkpoint path: ${LLAMA_CHECKPOINT_PATH}"

# Download checkpoint if missing
if [ ! -d "${LLAMA_CHECKPOINT_PATH}" ]; then
  echo "[entrypoint] No checkpoint found at ${LLAMA_CHECKPOINT_PATH}"
  
  if [ -n "${HF_TOKEN:-}" ]; then
    echo "[entrypoint] HF_TOKEN detected, downloading fishaudio/openaudio-s1-mini ..."
    python3 - <<'PY'
import os
from huggingface_hub import snapshot_download

token = os.environ.get("HF_TOKEN")
repo_id = "fishaudio/openaudio-s1-mini"
local_dir = os.environ.get("LLAMA_CHECKPOINT_PATH", "/app/checkpoints/openaudio-s1-mini")

print(f"[download] Downloading {repo_id} into {local_dir} ...")
snapshot_download(
    repo_id=repo_id,
    local_dir=local_dir,
    local_dir_use_symlinks=False,
    token=token,
)
print("[download] Download complete.")
PY
  else
    echo "[entrypoint] ERROR: HF_TOKEN not set and checkpoint missing."
    exit 1
  fi
fi

echo "[entrypoint] Starting Fish-Speech API server..."
exec python3 -m tools.api_server \
  --listen "${API_SERVER_HOST}:${API_SERVER_PORT}" \
  --llama-checkpoint-path "${LLAMA_CHECKPOINT_PATH}" \
  --decoder-checkpoint-path "${DECODER_CHECKPOINT_PATH}" \
  --decoder-config-name "${DECODER_CONFIG_NAME}" \
  ${COMPILE:+--compile}