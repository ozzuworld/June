#!/usr/bin/env bash
set -euo pipefail

echo "🚀 OpenVoice V2 end-to-end install (Python 3.10 venv)"; echo

# ---------- Settings ----------
MODEL_ID="${MODEL_ID:-myshell-ai/OpenVoiceV2}"
CHECKPOINTS_ROOT="${OPENVOICE_CHECKPOINTS_V2:-/models/openvoice/checkpoints_v2}"
VENV_DIR="${VENV_DIR:-/opt/openvoice/venv}"
OPENVOICE_SRC_DIR="${OPENVOICE_SRC_DIR:-/opt/openvoice/OpenVoice}"
PY_BIN="${PY_BIN:-python3.10}"

# ---------- System deps ----------
export DEBIAN_FRONTEND=noninteractive
apt-get update
if ! command -v python3.10 >/dev/null 2>&1; then
  apt-get install -y software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update
fi
apt-get install -y \
  python3.10 python3.10-venv python3.10-dev \
  build-essential git unzip wget curl libsndfile1 tree pkg-config \
  mecab libmecab-dev mecab-ipadic-utf8 || apt-get install -y mecab libmecab-dev mecab-ipadic mecab-utils

# ---------- Python venv (3.10) ----------
mkdir -p "$(dirname "$VENV_DIR")"
"$PY_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python - <<PY
import sys
assert sys.version_info[:2]==(3,10), f"Expected Python 3.10, got: {sys.version}"
print("Python OK:", sys.version)
PY

python -m pip install --upgrade pip wheel setuptools

# ---------- PyTorch ----------
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "🧠 GPU detected; installing PyTorch CUDA 12.1"
  pip install "torch>=2.3" --index-url https://download.pytorch.org/whl/cu121
else
  echo "🧠 No GPU detected; installing CPU PyTorch"
  pip install "torch>=2.3"
fi

# ---------- Core deps ----------
pip install fastapi "uvicorn[standard]" httpx soundfile numpy huggingface_hub

# ---------- MeCab + fugashi (pre-install to avoid MeloTTS failure) ----------
export MECAB_CONFIG=/usr/bin/mecab-config
mecab -v || { echo "MeCab missing"; exit 1; }
pip install --no-cache-dir 'fugashi[unidic-lite]==1.3.0' 'unidic-lite<1.1.0'
python - <<'PY'
import fugashi; print("fugashi OK:", getattr(fugashi, "__version__", "n/a"))
PY

# ---------- Force prebuilt tokenizers wheel (no Rust) ----------
pip install --upgrade pip wheel setuptools
export PIP_ONLY_BINARY=tokenizers
pip install --no-build-isolation --only-binary=:all: 'tokenizers==0.13.3'
# Pin transformers compatible with MeloTTS stack
pip install 'transformers==4.27.4'

# ---------- MeloTTS + OpenVoice ----------
pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git
python - <<'PY' || true
import subprocess, sys
try: subprocess.check_call([sys.executable, "-m", "unidic", "download"])
except Exception as e: print("unidic download skipped:", e)
PY

rm -rf "$OPENVOICE_SRC_DIR"
git clone https://github.com/myshell-ai/OpenVoice.git "$OPENVOICE_SRC_DIR"
pip install -e "$OPENVOICE_SRC_DIR"

# ---------- Fetch OpenVoice V2 assets ----------
mkdir -p "$CHECKPOINTS_ROOT"/{base_speakers,tone_color_converter}
python - <<PY
import os, shutil
from pathlib import Path
from huggingface_hub import snapshot_download

MODEL_ID = os.environ.get("MODEL_ID", "myshell-ai/OpenVoiceV2")
ROOT = Path(os.environ.get("OPENVOICE_CHECKPOINTS_V2", "$CHECKPOINTS_ROOT"))
BASE = ROOT / "base_speakers"
CONV = ROOT / "tone_color_converter"
BASE.mkdir(parents=True, exist_ok=True); CONV.mkdir(parents=True, exist_ok=True)

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
snapshot_download(repo_id=MODEL_ID, local_dir=str(ROOT), allow_patterns=patterns)

for alt in ("converter", "tone_color_converter_v2"):
    alt_dir = ROOT / alt
    if alt_dir.is_dir():
        for p in alt_dir.rglob("*"):
            if p.is_file():
                dst = CONV / p.name
                if not dst.exists(): shutil.copy2(p, dst)
        shutil.rmtree(alt_dir, ignore_errors=True)

root_cfg = ROOT / "config.json"
if root_cfg.exists(): shutil.move(str(root_cfg), str(CONV / "config.json"))
for ext in ("*.pt", "*.pth"):
    for p in ROOT.glob(ext):
        dst = CONV / p.name
        if not dst.exists(): shutil.move(str(p), str(dst))

deep_cfg = list(CONV.rglob("config.json"))
if deep_cfg and not (CONV / "config.json").exists():
    shutil.copy2(str(deep_cfg[0]), str(CONV / "config.json"))
deep_ckpt = list(CONV.rglob("*.pt")) + list(CONV.rglob("*.pth"))
if deep_ckpt:
    top = CONV / deep_ckpt[0].name
    if not top.exists(): shutil.copy2(str(deep_ckpt[0]), str(top))

missing=[]
if not (CONV / "config.json").exists(): missing.append("tone_color_converter/config.json")
if not list(CONV.glob("*.pt")) and not list(CONV.glob("*.pth")):
    missing.append("converter checkpoint (*.pt|*.pth) in tone_color_converter/")
if missing: raise SystemExit("❌ Missing: " + ", ".join(missing))
print("✅ Assets ready:", CONV / "config.json")
PY

echo; echo "🔍 Final layout:"
tree -L 3 "$CHECKPOINTS_ROOT" || true

echo; echo "✅ Install complete."
echo "   VENV:      $VENV_DIR"
echo "   OpenVoice: $OPENVOICE_SRC_DIR"
echo "   MODELS:    $CHECKPOINTS_ROOT"
echo
echo "👉 Before running your API:"
echo "   export OPENVOICE_CHECKPOINTS_V2=\"$CHECKPOINTS_ROOT\""
echo "   export CORS_ALLOW_ORIGINS=\"*\"   # or your domains"
echo "   source \"$VENV_DIR/bin/activate\""
echo "   uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1   # from your june-tts repo root"
