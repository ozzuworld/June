#!/usr/bin/env bash
set -euo pipefail

# Defaults (can be overridden with env)
: "${LLAMA_CHECKPOINT_PATH:=/app/checkpoints/openaudio-s1-mini}"
: "${DECODER_CHECKPOINT_PATH:=/app/checkpoints/openaudio-s1-mini/codec.pth}"
: "${DECODER_CONFIG_NAME:=modded_dac_vq}"
: "${API_SERVER_HOST:=0.0.0.0}"
: "${API_SERVER_PORT:=8080}"

echo "[entrypoint] Checkpoint path: ${LLAMA_CHECKPOINT_PATH}"

# 1) Ensure checkpoint exists (download if missing and HF_TOKEN is provided)
if [ ! -d "${LLAMA_CHECKPOINT_PATH}" ]; then
  echo "[entrypoint] No checkpoint found at ${LLAMA_CHECKPOINT_PATH}"

  if [ -n "${HF_TOKEN:-}" ]; then
    echo "[entrypoint] HF_TOKEN detected, trying to download fishaudio/openaudio-s1-mini ..."
    python3 - <<'PY'
import os
from huggingface_hub import snapshot_download

token = os.environ.get("HF_TOKEN")
if not token:
    raise SystemExit("HF_TOKEN is not set in the environment.")

repo_id = "fishaudio/openaudio-s1-mini"
local_dir = os.environ.get("LLAMA_CHECKPOINT_PATH", "/app/checkpoints/openaudio-s1-mini")

print(f"[download] Downloading {repo_id} into {local_dir} ...")
try:
    snapshot_download(
        repo_id=repo_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,
        token=token,
    )
except Exception as e:
    print(f"[download] Error while downloading model: {e}")
    print("[download] Make sure you:")
    print("  1) Are logged into HuggingFace with this token")
    print("  2) Have requested and been granted access to fishaudio/openaudio-s1-mini")
    raise
print("[download] Download complete.")
PY
  else
    echo "[entrypoint] ERROR: HF_TOKEN not set and checkpoint missing."
    echo "[entrypoint] Either:"
    echo "  - Run with:  -e HF_TOKEN=YOUR_HF_TOKEN"
    echo "    (and make sure your HF account has access to fishaudio/openaudio-s1-mini)"
    echo "  - Or mount an existing checkpoint dir at ${LLAMA_CHECKPOINT_PATH}"
    exit 1
  fi
else
  echo "[entrypoint] Checkpoint directory already exists, skipping download."
fi

echo "[entrypoint] Starting Fish-Speech API server..."
python3 -m tools.api_server \
  --listen "${API_SERVER_HOST}:${API_SERVER_PORT}" \
  --llama-checkpoint-path "${LLAMA_CHECKPOINT_PATH}" \
  --decoder-checkpoint-path "${DECODER_CHECKPOINT_PATH}" \
  --decoder-config-name "${DECODER_CONFIG_NAME}" \
  ${COMPILE:+--compile} &

FISH_PID=$!

# Small delay to let the model server start
sleep 5

echo "[entrypoint] Starting June TTS FastAPI service..."
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
