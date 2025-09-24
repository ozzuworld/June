#!/usr/bin/env bash
set -euo pipefail

ROOT="/workspace/june-tts"
ENV_FILE="${ROOT}/.env"
VENV="/opt/openvoice/venv"

_load_env() { set -a; source "${ENV_FILE}"; set +a; }
_activate() { source "${VENV}/bin/activate"; }

cmd="${1:-help}"

case "$cmd" in
  env)
    cat "${ENV_FILE}"
    ;;

  status)
    # show if port is listening
    _load_env
    echo "Expecting server bound on ${HOST}:${PORT}"
    (command -v ss >/dev/null && ss -ltnp "sport = :${PORT}" || lsof -iTCP -sTCP:LISTEN -P -n || true)
    ;;

  list-speakers)
    _load_env; _activate
    python - <<'PY'
from melo.api import TTS
import json
m = TTS(language="EN")
# prefer hps.data.spk2id; fall back to m.spk2id; ensure it's a plain dict
spk_map = {}
try:
    spk_map = getattr(getattr(getattr(m,"hps",None),"data",None),"spk2id",None) or {}
except Exception:
    pass
if not isinstance(spk_map, dict):
    spk_map = getattr(m, "spk2id", {}) if isinstance(getattr(m, "spk2id", {}), dict) else {}
print(json.dumps(spk_map, indent=2))
PY
    ;;

  set-speaker)
    # usage: ./day2-tools.sh set-speaker 3
    sid="${2:-0}"
    tmp="$(mktemp)"
    awk -v sid="$sid" '
      BEGIN { set=0 }
      /^MELO_SPEAKER_ID=/ { print "MELO_SPEAKER_ID=" sid; set=1; next }
      { print }
      END { if(!set) print "MELO_SPEAKER_ID=" sid }
    ' "${ENV_FILE}" > "$tmp" && mv "$tmp" "${ENV_FILE}"
    echo "MELO_SPEAKER_ID set to ${sid} in ${ENV_FILE}"
    ;;

  swap-base-en)
    # usage: ./day2-tools.sh swap-base-en en-us.pth
    _load_env
    file="${2:-en-us.pth}"
    dir="${OPENVOICE_CHECKPOINTS_V2}/base_speakers/ses"
    test -d "$dir" || { echo "Missing $dir"; exit 1; }
    cd "$dir"
    rm -f en-default.pth
    ln -s "$file" en-default.pth
    echo "en-default.pth -> $file"
    ls -l en-*.pth
    ;;

  smoke)
    # end-to-end test hitting /tts/generate -> out.wav
    _load_env
    # IMPORTANT: use HOST_FOR_CLIENT (defaults to 127.0.0.1), not the bind address 0.0.0.0
    url="http://${HOST_FOR_CLIENT:-127.0.0.1}:${PORT:-8000}/tts/generate"
    json='{
      "text":"OpenVoice V2 end-to-end smoke test.",
      "language":"en",
      "reference_url":"https://cdn.jsdelivr.net/gh/myshell-ai/OpenVoice/resources/example_reference.mp3",
      "speed":1.0, "volume":1.0, "pitch":0.0, "metadata": {}
    }'
    curl -sS -X POST "$url" -H 'Content-Type: application/json' -o out.wav -d "$json" && \
    (command -v soxi >/dev/null 2>&1 && soxi out.wav || file out.wav || true)
    ;;

  help|*)
    cat <<HLP
Usage: $0 <command>

Commands:
  env                  Show current .env
  status               Show if the API port is listening
  list-speakers        Print available speaker map from Melo (safe serialization)
  set-speaker <id>     Set MELO_SPEAKER_ID in .env (int; default 0)
  swap-base-en <pth>   Point en-default.pth symlink to a specific base file (e.g., en-us.pth)
  smoke                One-shot curl hitting /tts/generate -> out.wav
HLP
    ;;
esac
