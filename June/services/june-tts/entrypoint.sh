#!/usr/bin/env bash
set -euo pipefail

# Defaults (can be overridden with env)
: "${LLAMA_CHECKPOINT_PATH:=/app/checkpoints/openaudio-s1-mini}"
: "${DECODER_CHECKPOINT_PATH:=/app/checkpoints/openaudio-s1-mini/codec.pth}"
: "${DECODER_CONFIG_NAME:=modded_dac_vq}"
: "${API_SERVER_HOST:=0.0.0.0}"
: "${API_SERVER_PORT:=8080}"

echo "[entrypoint] Using checkpoint: ${LLAMA_CHECKPOINT_PATH}"

echo "[entrypoint] Starting Fish-Speech API server..."
python -m tools.api_server \
  --listen "${API_SERVER_HOST}:${API_SERVER_PORT}" \
  --llama-checkpoint-path "${LLAMA_CHECKPOINT_PATH}" \
  --decoder-checkpoint-path "${DECODER_CHECKPOINT_PATH}" \
  --decoder-config-name "${DECODER_CONFIG_NAME}" \
  ${COMPILE:+--compile} &

FISH_PID=$!

# Give the model server a moment to boot
sleep 5

echo "[entrypoint] Starting June TTS FastAPI service..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
