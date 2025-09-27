#!/bin/bash
# cleanup-orchestrator.sh
# Remove all redundant and confusing files from the June orchestrator

set -euo pipefail

echo "🧹 Cleaning up June Orchestrator directory"
echo "=========================================="

ORCHESTRATOR_DIR="June/services/june-orchestrator"

if [ ! -d "$ORCHESTRATOR_DIR" ]; then
    echo "❌ Directory $ORCHESTRATOR_DIR not found"
    exit 1
fi

cd "$ORCHESTRATOR_DIR"

echo "📂 Current directory: $(pwd)"

# Backup the clean files first
echo "💾 Backing up clean files..."
mkdir -p .cleanup-backup
cp app.py .cleanup-backup/app_original.py 2>/dev/null || echo "No app.py to backup"

# Remove all backup and redundant files
echo "🗑️  Removing backup and redundant files..."

# Remove backup app files
rm -f app_broken_backup.py
rm -f app_simple_backup.py
rm -f app_clean.py
rm -f app_tts_patch.py

# Remove backup requirements
rm -f requirements_broken_backup.txt
rm -f requirements_clean.txt

# Remove backup Dockerfiles
rm -f Dockerfile_clean

# Remove backup directories
rm -rf backup-20250926-183229/
rm -rf unitest/

# Remove various other backup and temp files
rm -f *.backup
rm -f *.bak
rm -f *.old
rm -f *.tmp

# Remove Python cache
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "*.pyo" -delete 2>/dev/null || true

# Remove unnecessary modules and directories
echo "📁 Removing unnecessary modules..."
rm -rf conversation_manager.py
rm -rf enhanced_conversation_manager.py
rm -rf external_tts_client.py
rm -rf media_apis.py
rm -rf models.py
rm -rf token_service.py
rm -rf tts_service.py
rm -rf tools.py
rm -rf voice_ws.py
rm -rf schemas/

# List remaining files
echo ""
echo "📋 Remaining files:"
ls -la

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "📁 Remaining structure should be:"
echo "   ├── app.py (clean implementation)"
echo "   ├── requirements.txt (minimal dependencies)"
echo "   ├── Dockerfile (optimized)"
echo "   ├── .env (your environment variables)"
echo "   └── .cleanup-backup/ (backup of original files)"
echo ""
echo "🚀 Next steps:"
echo "   1. Replace app.py with the clean implementation"
echo "   2. Replace requirements.txt with minimal dependencies"  
echo "   3. Replace Dockerfile with optimized version"
echo "   4. Test locally: python app.py"
echo "   5. Build and deploy: docker build -t orchestrator ."