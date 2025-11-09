#!/bin/bash

DB_NAME="keycloak"
NAMESPACE="june-services"
POD_NAME="postgresql-0"

echo "=== Step 1: Creating tts_voices table ==="
kubectl exec $POD_NAME -n $NAMESPACE -- psql -U keycloak -d $DB_NAME <<'EOF'
CREATE TABLE IF NOT EXISTS tts_voices (
    voice_id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    audio_data BYTEA NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tts_voices_name ON tts_voices(name);
EOF

if [ $? -ne 0 ]; then
    echo "❌ Failed to create table"
    exit 1
fi

echo "✅ Table created successfully"

echo ""
echo "=== Step 2: Verifying table exists ==="
kubectl exec $POD_NAME -n $NAMESPACE -- psql -U keycloak -d $DB_NAME -c "\d tts_voices"

if [ $? -ne 0 ]; then
    echo "❌ Table verification failed"
    exit 1
fi

echo ""
echo "=== Step 3: Copying WAV file to pod ==="
kubectl cp June/services/june-tts/app/references/June.wav \
  $NAMESPACE/$POD_NAME:/tmp/June.wav

if [ $? -ne 0 ]; then
    echo "❌ Failed to copy WAV file"
    exit 1
fi

echo "✅ WAV file copied"

echo ""
echo "=== Step 4: Inserting audio data into database ==="
kubectl exec $POD_NAME -n $NAMESPACE -- psql -U keycloak -d $DB_NAME <<'EOF'
INSERT INTO tts_voices (voice_id, name, audio_data)
VALUES (
    'default',
    'June Default',
    pg_read_binary_file('/tmp/June.wav')
)
ON CONFLICT (voice_id) DO UPDATE 
SET audio_data = EXCLUDED.audio_data,
    name = EXCLUDED.name,
    updated_at = CURRENT_TIMESTAMP;
EOF

if [ $? -ne 0 ]; then
    echo "❌ Failed to insert audio data"
    exit 1
fi

echo "✅ Audio data inserted"

echo ""
echo "=== Step 5: Verifying insert ==="
kubectl exec $POD_NAME -n $NAMESPACE -- psql -U keycloak -d $DB_NAME -c \
  "SELECT voice_id, name, length(audio_data) as audio_size_bytes, created_at FROM tts_voices;"

if [ $? -ne 0 ]; then
    echo "❌ Verification failed"
    exit 1
fi

echo ""
echo "=== Step 6: Cleaning up temporary file ==="
kubectl exec $POD_NAME -n $NAMESPACE -- rm /tmp/June.wav

echo ""
echo "=== Step 7: Restarting TTS service ==="
kubectl rollout restart deployment/june-tts -n $NAMESPACE

echo ""
echo "✅ Done! Check the TTS service logs with:"
echo "kubectl logs -f deployment/june-tts -n $NAMESPACE"
