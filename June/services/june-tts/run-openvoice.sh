#!/usr/bin/env bash
set -euo pipefail
cd /workspace/june-tts
set -a; source ./.env; set +a
source /opt/openvoice/venv/bin/activate

echo "Starting OpenVoice API on ${HOST}:${PORT} (workers=${WORKERS})"
exec uvicorn app.main:app --host "${HOST}" --port "${PORT}" --workers "${WORKERS}"
