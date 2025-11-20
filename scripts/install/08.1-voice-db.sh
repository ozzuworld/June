#!/bin/bash
set -e  # Exit on error

# Get the repository root (assumes script is in scripts/install/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VOICE_FILE="$REPO_ROOT/June/services/june-tts/app/references/June.wav"

echo "📁 Repository root: $REPO_ROOT"
echo "🎵 Voice file path: $VOICE_FILE"

# Verify the voice file exists
if [ ! -f "$VOICE_FILE" ]; then
    echo "❌ ERROR: Voice file not found at $VOICE_FILE"
    exit 1
fi

echo "✅ Voice file found ($(du -h "$VOICE_FILE" | cut -f1))"
echo ""

# 1. CREATE THE 'june' DATABASE
echo "🗄️  Creating 'june' database..."
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d keycloak -c "CREATE DATABASE june;" 2>/dev/null || echo "Database 'june' already exists"

# 2. CREATE THE TABLE IN THE 'june' DATABASE
echo "📋 Creating 'tts_voices' table..."
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "
CREATE TABLE IF NOT EXISTS tts_voices (
    voice_id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    audio_data BYTEA NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tts_voices_name ON tts_voices(name);
"

# 3. VERIFY THE TABLE EXISTS
echo "🔍 Verifying table exists..."
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "\dt"
echo ""

# 4. COPY THE WAV FILE
echo "📤 Copying voice file to PostgreSQL pod..."
kubectl cp "$VOICE_FILE" june-services/postgresql-0:/tmp/June.wav

echo "✅ Voice file copied to pod"
echo ""

# 5. INSERT THE DATA
echo "💾 Inserting voice data into database..."
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "
INSERT INTO tts_voices (voice_id, name, audio_data)
VALUES ('default', 'June Default', pg_read_binary_file('/tmp/June.wav'))
ON CONFLICT (voice_id) DO UPDATE SET
    audio_data = EXCLUDED.audio_data,
    updated_at = CURRENT_TIMESTAMP;
" && echo "✅ Voice 'default' inserted/updated successfully"
echo ""

# 6. VERIFY THE DATA
echo "🔍 Verifying data in database..."
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "
SELECT voice_id, name, length(audio_data) as size_bytes, created_at FROM tts_voices;
"
echo ""

# 7. CLEAN UP
echo "🧹 Cleaning up temporary file..."
kubectl exec postgresql-0 -n june-services -- rm /tmp/June.wav && echo "✅ Temporary file removed"
echo ""

# DONE
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ DONE! Database: june, Table: tts_voices"
echo "🎵 Default voice 'June Default' is ready for TTS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
