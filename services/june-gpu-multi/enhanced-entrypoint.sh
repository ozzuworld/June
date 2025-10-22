#!/bin/bash

# Enhanced June GPU Multi-Service Container Entrypoint
# Includes debug mode and detailed error logging

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Debug mode check
DEBUG_MODE=${DEBUG_MODE:-false}
if [[ "$DEBUG_MODE" == "true" ]]; then
    set -x  # Enable debug output
    echo -e "${YELLOW}[DEBUG] Enhanced debug mode enabled${NC}"
fi

echo "=========="
echo "== CUDA =="
echo "=========="
echo ""
echo "CUDA Version 11.8.0"
echo ""
echo "Container image Copyright (c) 2016-2023, NVIDIA CORPORATION & AFFILIATES. All rights reserved."
echo ""
echo "This container image and its contents are governed by the NVIDIA Deep Learning Container License."
echo "By pulling and using the container, you accept the terms and conditions of this license:"
echo "https://developer.nvidia.com/ngc/nvidia-deep-learning-container-license"
echo ""
echo "A copy of this license is made available in this container at /NGC-DL-CONTAINER-LICENSE for your convenience."
echo ""

echo -e "${BLUE}[INIT] Starting June GPU Multi-Service Container with Enhanced Debugging${NC}"
echo -e "${BLUE}[INIT] Timestamp: $(date)${NC}"

# GPU Detection with error handling
echo -e "${BLUE}[INIT] GPU Detection:${NC}"
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,uuid --format=csv,noheader | while IFS=, read -r name uuid; do
        gpu_num=$(nvidia-smi --query-gpu=index --format=csv,noheader,nounits | head -1)
        echo "GPU $gpu_num: $name (UUID: $uuid)"
    done
else
    echo -e "${RED}[ERROR] nvidia-smi not available - GPU access may be broken${NC}"
fi

# Environment Variables
echo -e "${BLUE}[INIT] Environment Variables:${NC}"
echo "  STT_PORT: ${STT_PORT:-8001}"
echo "  TTS_PORT: ${TTS_PORT:-8000}"
echo "  CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-0}"
echo "  WHISPER_DEVICE: ${WHISPER_DEVICE:-cuda}"
echo "  TTS_HOME: ${TTS_HOME:-/app/models}"
echo "  PYTHONPATH: ${PYTHONPATH:-/app:/app/stt:/app/tts}"
echo "  TAILSCALE_AUTH_KEY: ${TAILSCALE_AUTH_KEY:-<not set>}"
echo "  DEBUG_MODE: ${DEBUG_MODE:-false}"

# Enhanced directory validation
echo -e "${BLUE}[INIT] Validating directories...${NC}"
directories=("/app/models" "/app/cache" "/var/log/supervisor" "/var/run" "/var/lib/tailscale" "/var/run/tailscale")
for dir in "${directories[@]}"; do
    if [ -d "$dir" ]; then
        echo -e "  ${GREEN}✓${NC} $dir exists"
        # Check permissions
        if [ -w "$dir" ]; then
            echo -e "    ${GREEN}✓${NC} Writable"
        else
            echo -e "    ${YELLOW}⚠${NC} Not writable - fixing permissions"
            chmod 755 "$dir" 2>/dev/null || echo -e "    ${RED}✗${NC} Failed to fix permissions"
        fi
    else
        echo -e "  ${RED}✗${NC} $dir missing - creating"
        mkdir -p "$dir" && echo -e "    ${GREEN}✓${NC} Created" || echo -e "    ${RED}✗${NC} Failed to create"
    fi
done

# Python and package validation
echo -e "${BLUE}[INIT] Python version: $(python3 --version)${NC}"
echo -e "${BLUE}[INIT] Checking critical packages...${NC}"
packages=("fastapi" "uvicorn" "torch" "faster-whisper" "coqui-tts")
for package in "${packages[@]}"; do
    if python3 -c "import $package" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $package"
    else
        echo -e "  ${RED}✗${NC} $package - MISSING OR BROKEN"
        echo -e "    ${YELLOW}Attempting to install $package...${NC}"
        pip install "$package" --no-cache-dir --quiet || echo -e "    ${RED}✗${NC} Installation failed"
    fi
done

# Enhanced file validation
echo -e "${BLUE}[INIT] Validating service files...${NC}"
critical_files=("/app/stt/main.py" "/app/tts/main.py" "/etc/supervisor/conf.d/supervisord.conf" "/app/tailscale-connect.sh")
for file in "${critical_files[@]}"; do
    if [ -f "$file" ]; then
        echo -e "  ${GREEN}✓${NC} $file exists"
        # Check if Python files have syntax errors
        if [[ "$file" == *.py ]]; then
            if python3 -m py_compile "$file" 2>/dev/null; then
                echo -e "    ${GREEN}✓${NC} Syntax OK"
            else
                echo -e "    ${RED}✗${NC} SYNTAX ERROR in $file"
                python3 -m py_compile "$file" 2>&1 | head -3
            fi
        fi
    else
        echo -e "  ${RED}✗${NC} $file missing"
    fi
done

# GPU accessibility test
echo -e "${BLUE}[INIT] Testing GPU accessibility...${NC}"
python3 -c "
import torch
try:
    if torch.cuda.is_available():
        device_count = torch.cuda.device_count()
        print(f'  ${GREEN}✓${NC} CUDA available with {device_count} device(s)')
        for i in range(device_count):
            name = torch.cuda.get_device_name(i)
            memory = torch.cuda.get_device_properties(i).total_memory / 1e9
            print(f'    GPU {i}: {name} ({memory:.1f}GB)')
        # Test tensor operation
        x = torch.tensor([1.0]).cuda()
        print(f'  ${GREEN}✓${NC} GPU tensor operations work')
    else:
        print(f'  ${RED}✗${NC} CUDA not available')
except Exception as e:
    print(f'  ${RED}✗${NC} GPU test failed: {e}')
" 2>&1

echo -e "${BLUE}[INIT] Pre-flight checks completed ✓${NC}"

# Enhanced Tailscale handling
if [ -n "$TAILSCALE_AUTH_KEY" ] && [ "$TAILSCALE_AUTH_KEY" != "" ]; then
    echo -e "${BLUE}[TAILSCALE] Starting Tailscale connection...${NC}"
    if [ -f "/app/tailscale-connect.sh" ]; then
        bash /app/tailscale-connect.sh
    else
        echo -e "${YELLOW}[TAILSCALE] tailscale-connect.sh not found, skipping${NC}"
    fi
else
    echo -e "${YELLOW}[TAILSCALE] No auth key provided, skipping Tailscale connection${NC}"
fi

# Enhanced Supervisor startup with error handling
echo -e "${BLUE}[INIT] Starting AI services with Supervisor...${NC}"

# If debug mode, run the debug script first
if [[ "$DEBUG_MODE" == "true" ]] && [ -f "/app/debug-services.sh" ]; then
    echo -e "${YELLOW}[DEBUG] Running diagnostic script...${NC}"
    chmod +x /app/debug-services.sh
    /app/debug-services.sh
    echo -e "${YELLOW}[DEBUG] Diagnostic complete, proceeding with startup${NC}"
fi

# Create enhanced supervisor config with better logging
cat > /etc/supervisor/conf.d/supervisord.conf << 'EOF'
[supervisord]
nodaemon=true
user=root
logfile=/var/log/supervisor/supervisord.log
logfile_maxbytes=50MB
logfile_backups=10
loglevel=info
pidfile=/var/run/supervisord.pid

[program:june-stt]
command=python3 /app/stt/main.py
directory=/app
user=root
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/var/log/supervisor/june-stt.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
environment=PYTHONPATH=/app:/app/stt:/app/tts,CUDA_VISIBLE_DEVICES=%(ENV_CUDA_VISIBLE_DEVICES)s,STT_PORT=%(ENV_STT_PORT)s

[program:june-tts]
command=python3 /app/tts/main.py
directory=/app
user=root
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/var/log/supervisor/june-tts.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
environment=PYTHONPATH=/app:/app/stt:/app/tts,CUDA_VISIBLE_DEVICES=%(ENV_CUDA_VISIBLE_DEVICES)s,TTS_PORT=%(ENV_TTS_PORT)s
EOF

echo -e "${GREEN}[INIT] Enhanced supervisor config created${NC}"

# Start supervisor with error handling
echo -e "${BLUE}[SUPERVISOR] Starting supervisord...${NC}"
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
