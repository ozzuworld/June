#!/bin/bash
# cleanup-script.sh - Clean up TTS confusion and prepare for Chatterbox

echo "í·¹ Cleaning up TTS service confusion..."

# Remove the confused chatterbox-tts directory (it was actually using Coqui)
if [ -d "June/services/june-chatterbox-tts" ]; then
    echo "Removing confused june-chatterbox-tts directory..."
    rm -rf June/services/june-chatterbox-tts/
fi

# Remove the old Terraform config
if [ -f "infra/envs/quarterly/chatterbox-tts.tf" ]; then
    echo "Removing old chatterbox Terraform config..."
    rm -f infra/envs/quarterly/chatterbox-tts.tf
fi

# Create proper directory structure for Chatterbox TTS
echo "Creating clean TTS service directory..."
mkdir -p June/services/june-tts/

echo "âœ… Cleanup complete! Ready for proper Chatterbox TTS implementation."
echo ""
echo "Next steps:"
echo "1. Implement new Chatterbox TTS service in June/services/june-tts/"
echo "2. Update deployment workflows"
echo "3. Update Terraform configurations"
echo "4. Test the new implementation"
