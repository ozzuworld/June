#!/bin/bash

DB_NAME="keycloak"  # Change if your database has a different name
NAMESPACE="june-services"
POD_NAME="postgresql-0"

echo "Creating tts_voices table..."
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

echo "Copying WAV file to pod..."
kubectl cp June/services/june-tts/app/references/June.wav \
  $NAMESPACE/$POD_NAME:/tmp/June.wav

echo "Inserting audio data into database..."
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

echo "Verifying insert..."
kubectl exec $POD_NAME -n $NAMESPACE -- psql -U keycloak -d $DB_NAME -c \
  "SELECT voice_id, name, length(audio_data) as audio_size_bytes, created_at FROM tts_voices;"

echo "Cleaning up temporary file..."
kubectl exec $POD_NAME -n $NAMESPACE -- rm /tmp/June.wav

echo "Restarting TTS service..."
kubectl rollout restart deployment/june-tts -n $NAMESPACE

echo "Done! Check the TTS service logs with:"
echo "kubectl logs -f deployment/june-tts -n $NAMESPACE"


