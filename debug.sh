#!/bin/bash
# Debug script for June TTS on Vast.ai
# Run this inside your container to diagnose the startup issue

echo "🔧 June TTS Container Diagnostics"
echo "=================================="

# Check basic system info
echo "📋 System Information"
echo "--------------------"
echo "Container ID: ${CONTAINER_ID:-not_set}"
echo "Python version: $(python --version 2>/dev/null || echo 'Python not found')"
echo "Current directory: $(pwd)"
echo "User: $(whoami)"
echo ""

# Check if Python packages are installed
echo "📦 Python Packages Check"
echo "------------------------"
python -c "import sys; print('Python executable:', sys.executable)" 2>/dev/null || echo "❌ Python import failed"
python -c "import fastapi; print('✅ FastAPI available:', fastapi.__version__)" 2>/dev/null || echo "❌ FastAPI not available"
python -c "import uvicorn; print('✅ Uvicorn available:', uvicorn.__version__)" 2>/dev/null || echo "❌ Uvicorn not available"
echo ""

# Check directory structure
echo "📁 Directory Structure"
echo "---------------------"
echo "Contents of /workspace:"
ls -la /workspace/ 2>/dev/null || echo "❌ /workspace not found"
echo ""
echo "Contents of current directory:"
ls -la . 2>/dev/null || echo "❌ Current directory not accessible"
echo ""

# Check if app exists
echo "🎯 Application Files"
echo "-------------------"
find /workspace -name "*.py" -type f 2>/dev/null | head -10 || echo "❌ No Python files found"
echo ""
if [ -f "/workspace/app/main.py" ]; then
    echo "✅ Found /workspace/app/main.py"
    ls -la /workspace/app/main.py
else
    echo "❌ /workspace/app/main.py not found"
fi
echo ""

# Check environment variables
echo "🌍 Environment Variables"
echo "------------------------"
env | grep -E "(PORT|HOST|PYTHON|PATH)" | sort
echo ""

# Try to start uvicorn manually
echo "🚀 Manual Uvicorn Test"
echo "---------------------"
echo "Testing uvicorn startup..."

# Try different possible app locations
POSSIBLE_APPS=(
    "app.main:app"
    "main:app"
    "app:app"
    "/workspace/app/main.py"
)

for app_path in "${POSSIBLE_APPS[@]}"; do
    echo "Testing: uvicorn $app_path --host 0.0.0.0 --port 8000"
    timeout 10s uvicorn "$app_path" --host 0.0.0.0 --port 8000 --workers 1 &
    UVICORN_PID=$!
    sleep 3
    
    if ps -p $UVICORN_PID > /dev/null 2>&1; then
        echo "✅ Uvicorn started successfully with $app_path"
        kill $UVICORN_PID 2>/dev/null || true
        break
    else
        echo "❌ Failed to start with $app_path"
    fi
done

echo ""

# Check if port 8000 is listening
echo "🔌 Port Check"
echo "------------"
netstat -tulpn 2>/dev/null | grep ":8000" || echo "❌ Port 8000 not listening"
echo ""

# Final recommendations
echo "💡 Recommendations"
echo "==================="
echo "1. Make sure the Dockerfile has a proper CMD instruction"
echo "2. Verify the app structure matches the import path"
echo "3. Check if all Python dependencies are installed"
echo "4. Try manually starting uvicorn with the correct app path"
echo ""

# Show how to manually start the service
echo "🔧 Manual Startup Commands to Try:"
echo "1. cd /workspace && uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo "2. python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo "3. python /workspace/app/main.py"