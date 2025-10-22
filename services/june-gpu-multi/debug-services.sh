#!/bin/bash

# Debug script for June GPU Multi-Service Container
# This script helps diagnose STT/TTS startup failures

echo "=== June GPU Multi Debug Script ==="
echo "Timestamp: $(date)"
echo "Running on: $(hostname)"
echo ""

# System info
echo "=== SYSTEM INFO ==="
echo "GPU Info:"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits 2>/dev/null || echo "nvidia-smi failed"
echo ""
echo "Python version: $(python3 --version)"
echo "CUDA available in Python:"
python3 -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA devices: {torch.cuda.device_count()}'); print(f'Current device: {torch.cuda.current_device() if torch.cuda.is_available() else "N/A"}')" 2>&1
echo ""

# Environment variables
echo "=== ENVIRONMENT VARIABLES ==="
echo "STT_PORT: $STT_PORT"
echo "TTS_PORT: $TTS_PORT"
echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"
echo "WHISPER_DEVICE: $WHISPER_DEVICE"
echo "TTS_HOME: $TTS_HOME"
echo "PYTHONPATH: $PYTHONPATH"
echo ""

# Directory checks
echo "=== DIRECTORY CHECKS ==="
for dir in "/app" "/app/stt" "/app/tts" "/app/models" "/app/cache"; do
    if [ -d "$dir" ]; then
        echo "✓ $dir exists ($(ls -la "$dir" | wc -l) items)"
        ls -la "$dir" | head -5
    else
        echo "✗ $dir missing"
    fi
done
echo ""

# File checks
echo "=== CRITICAL FILE CHECKS ==="
for file in "/app/stt/main.py" "/app/tts/main.py" "/etc/supervisor/conf.d/supervisord.conf"; do
    if [ -f "$file" ]; then
        echo "✓ $file exists ($(stat -c%s "$file") bytes)"
    else
        echo "✗ $file missing"
    fi
done
echo ""

# Port checks
echo "=== PORT AVAILABILITY ==="
for port in 8000 8001; do
    if netstat -tlnp 2>/dev/null | grep -q ":$port "; then
        echo "⚠ Port $port already in use:"
        netstat -tlnp 2>/dev/null | grep ":$port "
    else
        echo "✓ Port $port available"
    fi
done
echo ""

# Python import tests
echo "=== PYTHON IMPORT TESTS ==="
echo "Testing critical imports..."
for module in "fastapi" "uvicorn" "torch" "faster_whisper" "TTS"; do
    python3 -c "import $module; print(f'✓ {module} imported successfully')" 2>/dev/null || echo "✗ $module import failed"
done
echo ""

# Test GPU access in Python
echo "=== GPU ACCESS TEST ==="
python3 -c "
import torch
if torch.cuda.is_available():
    device = torch.device('cuda:0')
    print(f'✓ GPU {torch.cuda.get_device_name(0)} accessible')
    x = torch.tensor([1.0]).to(device)
    print(f'✓ Tensor operations on GPU work: {x}')
else:
    print('✗ CUDA not available')
" 2>&1
echo ""

# Manual service startup test
echo "=== MANUAL SERVICE STARTUP TEST ==="
echo "Testing STT service startup..."
cd /app
(timeout 10 python3 stt/main.py 2>&1 || echo "STT startup failed") &
stt_pid=$!
echo "STT PID: $stt_pid"

echo "Testing TTS service startup..."
(timeout 10 python3 tts/main.py 2>&1 || echo "TTS startup failed") &
tts_pid=$!
echo "TTS PID: $tts_pid"

# Wait for tests and capture output
echo "Waiting for startup tests..."
sleep 12
echo ""

# Check supervisor logs if they exist
echo "=== SUPERVISOR LOGS (last 10 lines each) ==="
for log in "/var/log/supervisor/june-stt.log" "/var/log/supervisor/june-tts.log" "/var/log/supervisor/supervisord.log"; do
    if [ -f "$log" ]; then
        echo "--- $log ---"
        tail -10 "$log" 2>/dev/null
        echo ""
    else
        echo "$log not found"
    fi
done

echo "=== DEBUG COMPLETE ==="
echo "If services are failing, check the errors above."
echo "Common issues:"
echo "- CUDA/GPU access problems"
echo "- Missing Python packages"
echo "- Port conflicts"
echo "- File permission issues"
echo "- Missing model files"
