# Enforce Python 3.10 venv for compatibility with transformers==4.27.x / tokenizers<0.14
PY_BIN=${PY_BIN:-python3.10}
VENV_DIR=${VENV_DIR:-/opt/openvoice/venv}

# Enforce Python 3.10 venv for compatibility with transformers==4.27.x / tokenizers<0.14
PY_BIN=${PY_BIN:-python3.10}
VENV_DIR=${VENV_DIR:-/opt/openvoice/venv}

#!/usr/bin/env bash
set -euo pipefail

echo "🚀 OpenVoice V2 end-to-end install (venv)"; echo

# ---- Settings (override via env if needed) ----
MODEL_ID="${MODEL_ID:-myshell-ai/OpenVoiceV2}"
CHECKPOINTS_ROOT="${OPENVOICE_CHECKPOINTS_V2:-/models/openvoice/checkpoints_v2}"
VENV_DIR="${VENV_DIR:-/opt/openvoice/venv}"
OPENVOICE_SRC_DIR="${OPENVOICE_SRC_DIR:-/opt/openvoice/OpenVoice}"

# ---- System deps ----
apt-get update
apt-get install -y python3-venv python3-dev build-essential git unzip wget curl \
                   libsndfile1 tree

# ---- Python venv ----
mkdir -p "$(dirname "$VENV_DIR")"
"$PY_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip wheel setuptools

# ---- PyTorch (GPU if present) ----
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "🧠 GPU detected; installing PyTorch CUDA 12.1 wheels"
  pip install "torch>=2.3" --index-url https://download.pytorch.org/whl/cu121
else
  echo "🧠 No GPU detected; installing CPU PyTorch"
  pip install "torch>=2.3"
fi

# ---- Core deps ----
pip install fastapi uvicorn[standard] httpx soundfile numpy huggingface_hub

# --- MeCab system deps for fugashi ---
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y pkg-config mecab libmecab-dev mecab-ipadic-utf8 || apt-get install -y pkg-config mecab libmecab-dev mecab-ipadic mecab-utils

# --- Pre-install fugashi + small dictionary (so MeloTTS won't fail) ---
export MECAB_CONFIG=/usr/bin/mecab-config
pip install --no-cache-dir 'fugashi[unidic-lite]==1.3.0' 'unidic-lite<1.1.0'

# --- Quick sanity checks (fail fast if MeCab/fugashi are broken) ---
mecab -v || { echo 'MeCab missing'; exit 1; }
python - <<'PY' || { echo 'fugashi import failed'; exit 1; }
import fugashi; print('fugashi OK')
PY
# --- Ensure prebuilt wheels for tokenizers (avoid Rust build) ---
# Use the current Python/pip in this script context.
python - <<'PY'
import sys
print("Python exec:", sys.executable)
PY
pip install --upgrade pip wheel setuptools
# Force binary wheel for tokenizers; 0.15.2 has manylinux wheels for py3.8–3.11
# If your env is py3.12, manylinux wheels exist for newer versions, but some stacks still pull sources.
# This pin keeps us on a known-good wheel and avoids rustc/cargo.
export PIP_ONLY_BINARY=tokenizers
pip install --no-build-isolation --only-binary=:all: 'tokenizers==0.15.2'
# Optional: keep transformers in a range compatible with that tokenizers
pip install 'transformers<4.45'
# --- MeCab system deps for fugashi ---
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y pkg-config mecab libmecab-dev mecab-ipadic-utf8 || apt-get install -y pkg-config mecab libmecab-dev mecab-ipadic mecab-utils

# --- Pre-install fugashi + small dictionary (so MeloTTS won’t fail) ---
export MECAB_CONFIG=/usr/bin/mecab-config
pip install --no-cache-dir 'fugashi[unidic-lite]==1.3.0' 'unidic-lite<1.1.0'

# --- Quick sanity checks ---
mecab -v || { echo 'MeCab missing'; exit 1; }
python - <<'PY' || { echo 'fugashi import failed'; exit 1; }
import fugashi; print('fugashi OK')
PY
# ---- MeloTTS + OpenVoice ----
pip install git+https://github.com/myshell-ai/MeloTTS.git
python - <<'PY' || true
import subprocess, sys
try: subprocess.check_call([sys.executable, "-m", "unidic", "download"])
except Exception as e: print("unidic download skipped:", e)
PY

rm -rf "$OPENVOICE_SRC_DIR"
git clone https://github.com/myshell-ai/OpenVoice.git "$OPENVOICE_SRC_DIR"
pip install -e "$OPENVOICE_SRC_DIR"

# ---- Fetch OpenVoice V2 assets (robust, handles folder name variants) ----
mkdir -p "$CHECKPOINTS_ROOT"/{base_speakers,tone_color_converter}

python - <<PY
import os, shutil
from pathlib import Path
from huggingface_hub import snapshot_download

MODEL_ID = os.environ.get("MODEL_ID", "myshell-ai/OpenVoiceV2")
ROOT = Path(os.environ.get("OPENVOICE_CHECKPOINTS_V2", "$CHECKPOINTS_ROOT"))
BASE = ROOT / "base_speakers"
CONV = ROOT / "tone_color_converter"
BASE.mkdir(parents=True, exist_ok=True)
CONV.mkdir(parents=True, exist_ok=True)

# Pull likely folders/files regardless of card layout
patterns = [
    "base_speakers/*",
    "tone_color_converter/*",
    "converter/*",
    "tone_color_converter_v2/*",
    "config.json",
    "*.pt",
    "*.pth",
]
print(f"📥 Downloading from {MODEL_ID} into {ROOT} ...")
snapshot_download(
    repo_id=MODEL_ID,
    local_dir=str(ROOT),
    local_dir_use_symlinks=False,
    allow_patterns=patterns,
)

# Normalize possible alternative folder names into tone_color_converter/
for alt in ("converter", "tone_color_converter_v2"):
    alt_dir = ROOT / alt
    if alt_dir.is_dir():
        for p in alt_dir.rglob("*"):
            if p.is_file():
                dest = CONV / p.name
                if not dest.exists():
                    shutil.copy2(p, dest)
        shutil.rmtree(alt_dir, ignore_errors=True)

# Move any root-level assets into tone_color_converter/
root_cfg = ROOT / "config.json"
if root_cfg.exists():
    shutil.move(str(root_cfg), str(CONV / "config.json"))
for pattern in ("*.pt", "*.pth"):
    for p in ROOT.glob(pattern):
        dest = CONV / p.name
        if not dest.exists():
            shutil.move(str(p), str(dest))

# Promote deep config/ckpt to top-level if needed
deep_cfg = list(CONV.rglob("config.json"))
if deep_cfg and not (CONV / "config.json").exists():
    shutil.copy2(str(deep_cfg[0]), str(CONV / "config.json"))
deep_ckpt = list(CONV.rglob("*.pt")) + list(CONV.rglob("*.pth"))
if deep_ckpt:
    top_ckpt = CONV / deep_ckpt[0].name
    if not top_ckpt.exists():
        shutil.copy2(str(deep_ckpt[0]), str(top_ckpt))

# Verify
missing = []
if not (CONV / "config.json").exists():
    missing.append("tone_color_converter/config.json")
if not list(CONV.glob("*.pt")) and not list(CONV.glob("*.pth")):
    missing.append("converter checkpoint (*.pt|*.pth) in tone_color_converter/")
if missing:
    raise SystemExit("❌ Missing: " + ", ".join(missing))
print("✅ Assets ready:", CONV / "config.json", "and at least one ckpt")
PY

echo; echo "🔍 Final layout:"
tree -L 3 "$CHECKPOINTS_ROOT" || true

echo; echo "✅ Install complete."
echo "   VENV:      $VENV_DIR"
echo "   OpenVoice: $OPENVOICE_SRC_DIR"
echo "   MODELS:    $CHECKPOINTS_ROOT"
echo
echo "👉 Before running your API each boot:"
echo "   export OPENVOICE_CHECKPOINTS_V2=\"$CHECKPOINTS_ROOT\""
echo "   export CORS_ALLOW_ORIGINS=\"*\"   # or your domains"
echo "   source \"$VENV_DIR/bin/activate\""
