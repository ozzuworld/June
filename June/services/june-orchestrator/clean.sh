#!/bin/bash
# TTS Cleanup Script - Automated Migration
# Run this from the june-orchestrator directory

set -e  # Exit on error

echo "======================================"
echo "TTS Cleanup - Automated Migration"
echo "======================================"
echo ""

# Check if we're in the right directory
if [ ! -d "app/services" ]; then
    echo "❌ Error: Must run from june-orchestrator directory"
    echo "   cd June/services/june-orchestrator"
    exit 1
fi

echo "��� Current directory: $(pwd)"
echo ""

# Step 1: Backup
echo "Step 1: Creating backup..."
if [ -d "app.backup" ]; then
    echo "⚠️  Backup already exists (app.backup)"
    read -p "Overwrite? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Aborted"
        exit 1
    fi
    rm -rf app.backup
fi

cp -r app app.backup
echo "✅ Backup created: app.backup"
echo ""

# Step 2: Delete old files
echo "Step 2: Deleting old files..."
files_to_delete=(
    "app/services/external/tts.py"
    "app/voice_registry_old.py"
)

for file in "${files_to_delete[@]}"; do
    if [ -f "$file" ]; then
        rm "$file"
        echo "  ✅ Deleted: $file"
    else
        echo "  ⏭️  Not found: $file (already removed?)"
    fi
done
echo ""

# Step 3: Update files (manual step)
echo "Step 3: Update files (MANUAL)..."
echo "  Please copy the following files:"
echo ""
echo "  dependencies_cleaned.py    → app/core/dependencies.py"
echo "  external_init_cleaned.py   → app/services/external/__init__.py"
echo ""
echo "  (Optional enhancement):"
echo "  tts_service_enhanced.py    → app/services/tts_service.py"
echo ""
echo "  Run these commands:"
echo "  cp dependencies_cleaned.py app/core/dependencies.py"
echo "  cp external_init_cleaned.py app/services/external/__init__.py"
echo "  cp tts_service_enhanced.py app/services/tts_service.py  # optional"
echo ""
read -p "Press Enter after copying files..."
echo ""

# Step 4: Verify
echo "Step 4: Verifying cleanup..."
echo ""

# Check for old imports
echo "Checking for old TTSClient references..."
if grep -r "from.*tts import TTSClient" app/ 2>/dev/null | grep -v "app.backup"; then
    echo "⚠️  Warning: Found old TTSClient imports"
else
    echo "✅ No old TTSClient imports found"
fi

if grep -r "get_tts_client" app/ 2>/dev/null | grep -v "app.backup"; then
    echo "⚠️  Warning: Found get_tts_client references"
else
    echo "✅ No old get_tts_client references found"
fi

echo ""

# Step 5: Summary
echo "======================================"
echo "Cleanup Complete!"
echo "======================================"
echo ""
echo "Changes made:"
echo "  ✅ Deleted: app/services/external/tts.py"
echo "  ✅ Deleted: app/voice_registry_old.py"
echo "  ✅ Updated: app/core/dependencies.py"
echo "  ✅ Updated: app/services/external/__init__.py"
echo ""
echo "Backup available at: app.backup"
echo ""
echo "Next steps:"
echo "  1. Review the changes"
echo "  2. Restart the service:"
echo "     docker-compose restart june-orchestrator"
echo ""
echo "  3. Check logs:"
echo "     docker-compose logs -f june-orchestrator | grep TTS"
echo ""
echo "  4. Test TTS:"
echo "     curl http://localhost:8080/api/voices"
echo ""
echo "If issues occur, restore backup:"
echo "  rm -rf app && mv app.backup app"
echo ""
