#!/bin/bash
set -e

echo "1. Creating 'june' database..."
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d keycloak -c "CREATE DATABASE june;" || echo "Database might already exist"

echo "2. Creating tts_voices table in 'june' database..."
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

echo "3. Verifying table..."
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "\dt"

echo "4. Copying WAV file..."
kubectl cp June/services/june-tts/app/references/June.wav june-services/postgresql-0:/tmp/June.wav

echo "5. Inserting audio data..."
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "
INSERT INTO tts_voices (voice_id, name, audio_data)
VALUES ('default', 'June Default', pg_read_binary_file('/tmp/June.wav'))
ON CONFLICT (voice_id) DO UPDATE SET audio_data = EXCLUDED.audio_data, updated_at = CURRENT_TIMESTAMP;
"

echo "6. Verifying data..."
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "
SELECT voice_id, name, length(audio_data) as size_bytes, created_at FROM tts_voices;
"

echo "7. Cleaning up..."
kubectl exec postgresql-0 -n june-services -- rm /tmp/June.wav

echo "✅ DONE!"
echo "Your TTS service needs to connect to database 'june', not 'keycloak'"
