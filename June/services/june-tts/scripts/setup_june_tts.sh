#!/usr/bin/env bash
set -euo pipefail

APP_USER="june-tts"
APP_GROUP="june-tts"
APP_DIR="/opt/june-tts"
ENV_FILE="/etc/june-tts/june-tts.env"
SERVICE_FILE="/etc/systemd/system/june-tts.service"
PORT="8000"

echo "==> Installing OS dependencies"
apt-get update -y
apt-get install -y python3-venv python3-dev build-essential ffmpeg unzip

# Optional: CUDA hosts will want the right PyTorch wheel; CPU-only is fine too.
# If you need CUDA later, you can reinstall torch with the CUDA index URL.

echo "==> Creating app user and directories"
id -u "$APP_USER" >/dev/null 2>&1 || adduser --system --group --home "$APP_DIR" "$APP_USER"
mkdir -p "$APP_DIR" /etc/june-tts
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR" /etc/june-tts

echo "==> Copying project into $APP_DIR"
# Expect your zip is present where you run this. Adjust path if needed.
SRC_ZIP="$(pwd)/june-tts.zip"
if [ ! -f "$SRC_ZIP" ]; then
  echo "ERROR: Cannot find june-tts.zip in current directory: $(pwd)"
  exit 1
fi
# extract under /opt/june-tts
unzip -o "$SRC_ZIP" -d "$APP_DIR"
# The zip contains a top-level folder named 'june-tts'
APP_CODE_DIR="$APP_DIR/june-tts"

echo "==> Python venv + dependencies"
python3 -m venv "$APP_CODE_DIR/.venv"
source "$APP_CODE_DIR/.venv/bin/activate"
pip install --upgrade pip wheel

# Install core requirements
pip install -r "$APP_CODE_DIR/requirements.txt"

# Install torch CPU by default (safe everywhere). For CUDA, replace with the commented line below.
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
# For CUDA 12.1 hosts, use:
# pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install OpenVoice + MeloTTS (try PyPI first; if you use custom forks, swap for your git URLs)
# If these error on your host, install from your known sources/versions.
pip install openvoice || true
pip install melo-tts || true

deactivate

echo "==> Checkpoints"
# Extract model checkpoints to a stable path and point the app there
if [ -f "$APP_CODE_DIR/checkpoints_v2.zip" ]; then
  unzip -o "$APP_CODE_DIR/checkpoints_v2.zip" -d "$APP_DIR"
fi
# Expect resulting directory: /opt/june-tts/checkpoints_v2
if [ ! -d "$APP_DIR/checkpoints_v2" ]; then
  echo "WARNING: checkpoints_v2 directory not found after unzip. Place it at $APP_DIR/checkpoints_v2"
fi

echo "==> Environment file at $ENV_FILE"
cat >/etc/june-tts/june-tts.env <<'EOF'
# ===== June TTS runtime env =====
PORT=8000
LOG_LEVEL=INFO
WORKERS=1

# Force CPU unless you confirm CUDA works on this box:
FORCE_CPU=true
CUDA_VISIBLE_DEVICES=0

# OpenVoice checkpoints location (matches what we extracted)
CHECKPOINTS_PATH=/opt/june-tts/checkpoints_v2

# FastAPI/Service settings
ENVIRONMENT=production
API_TITLE="OpenVoice API"
API_VERSION="1.0.0"

# Keycloak (match names in config.py)
KEYCLOAK_SERVER_URL=https://june-idp.allsafe.world/auth
KEYCLOAK_REALM=june
KEYCLOAK_CLIENT_ID=external-tts-client
KEYCLOAK_CLIENT_SECRET=change-me
EOF

chown "$APP_USER:$APP_GROUP" "$ENV_FILE"
chmod 640 "$ENV_FILE"

echo "==> systemd unit"
cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=June TTS (OpenVoice API) service
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$APP_CODE_DIR
EnvironmentFile=$ENV_FILE
Environment=PYTHONPATH=$APP_CODE_DIR
# If you need a proxy or extra env, add more Environment= lines.

ExecStart=$APP_CODE_DIR/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=on-failure
RestartSec=5
# Harden a bit
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
EOF

echo "==> Reload + enable + start"
systemctl daemon-reload
systemctl enable june-tts
systemctl start june-tts

echo "==> Status"
systemctl --no-pager --full status june-tts || true

echo "==> Done. Try: curl -s http://127.0.0.1:$PORT/health | jq ."
