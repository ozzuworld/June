#!/bin/bash
# debug_openvoice.sh - Troubleshoot OpenVoice installation

echo "🔍 OpenVoice Installation Debug"
echo "================================"

# Check if container is running
echo "📦 Container Info:"
docker ps | grep june-tts || echo "No june-tts container running"
echo ""

# Get container ID
CONTAINER_ID=$(docker ps -q --filter "ancestor=ozzuworld/june-tts:latest" | head -1)

if [ -z "$CONTAINER_ID" ]; then
    echo "❌ No june-tts container found. Starting one for debugging..."
    CONTAINER_ID=$(docker run -d --name june-tts-debug ozzuworld/june-tts:latest sleep 3600)
    echo "✅ Started debug container: $CONTAINER_ID"
fi

echo "🔍 Debugging container: $CONTAINER_ID"
echo ""

# Check Python environment
echo "🐍 Python Environment:"
docker exec $CONTAINER_ID python -c "import sys; print('Python:', sys.executable); print('Path:', sys.path[:3])"
echo ""

# Check installed packages
echo "📦 Installed Packages (OpenVoice related):"
docker exec $CONTAINER_ID pip list | grep -i "openvoice\|melo\|torch" || echo "No matching packages found"
echo ""

# Check if OpenVoice source exists
echo "📁 OpenVoice Source Files:"
docker exec $CONTAINER_ID find /opt/venv -name "*openvoice*" -type d 2>/dev/null || echo "No OpenVoice directories in /opt/venv"
docker exec $CONTAINER_ID find /tmp -name "*OpenVoice*" -type d 2>/dev/null || echo "No OpenVoice directories in /tmp"
docker exec $CONTAINER_ID ls -la /workspace/ 2>/dev/null || echo "/workspace not accessible"
echo ""

# Check virtual environment
echo "🔧 Virtual Environment:"
docker exec $CONTAINER_ID ls -la /opt/venv/lib/python3.10/site-packages/ | grep -i openvoice || echo "OpenVoice not in site-packages"
echo ""

# Test direct import
echo "🧪 Direct Import Test:"
docker exec $CONTAINER_ID python -c "
try:
    import openvoice
    print('✅ openvoice module found at:', openvoice.__file__)
    print('✅ openvoice version:', getattr(openvoice, '__version__', 'unknown'))
except ImportError as e:
    print('❌ openvoice import failed:', e)

try:
    from openvoice.api import ToneColorConverter
    print('✅ ToneColorConverter import OK')
except ImportError as e:
    print('❌ ToneColorConverter import failed:', e)

try:
    from openvoice import se_extractor
    print('✅ se_extractor import OK')
except ImportError as e:
    print('❌ se_extractor import failed:', e)
"
echo ""

# Check if models exist
echo "📄 Model Files:"
docker exec $CONTAINER_ID find /models -name "*.pth" -o -name "*.pt" -o -name "config.json" 2>/dev/null | head -10 || echo "No model files found in /models"
echo ""

# Check build logs for OpenVoice installation
echo "🏗️ Build Process Check:"
docker exec $CONTAINER_ID python -c "
import subprocess
import sys

# Check if git is available (needed for OpenVoice install)
try:
    result = subprocess.run(['git', '--version'], capture_output=True, text=True)
    print('Git available:', result.stdout.strip() if result.returncode == 0 else 'No')
except:
    print('Git: Not available')

# Check if we can access OpenVoice repo
try:
    result = subprocess.run(['pip', 'show', 'openvoice'], capture_output=True, text=True)
    if result.returncode == 0:
        print('OpenVoice pip package:', result.stdout.split('\n')[0:3])
    else:
        print('OpenVoice not installed via pip')
except:
    print('pip show failed')
"

echo ""
echo "🔧 Recommended Next Steps:"
echo "1. If OpenVoice source is missing: Fix Dockerfile installation"
echo "2. If import fails: Check Python path and dependencies"
echo "3. If models missing: Fix model download process"
echo ""

# Cleanup debug container if we created it
if docker ps -a --format "table {{.Names}}" | grep -q "june-tts-debug"; then
    echo "🧹 Cleaning up debug container..."
    docker stop june-tts-debug >/dev/null 2>&1
    docker rm june-tts-debug >/dev/null 2>&1
fi