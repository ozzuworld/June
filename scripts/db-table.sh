# 1. CREATE THE 'june' DATABASE
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d keycloak -c "CREATE DATABASE june;"

# 2. CREATE THE TABLE IN THE 'june' DATABASE
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "
CREATE TABLE tts_voices (
    voice_id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    audio_data BYTEA NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_tts_voices_name ON tts_voices(name);
"

# 3. VERIFY THE TABLE EXISTS
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "\dt"

# 4. COPY THE WAV FILE
kubectl cp June/services/june-tts/app/references/June.wav june-services/postgresql-0:/tmp/June.wav

# 5. INSERT THE DATA
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "
INSERT INTO tts_voices (voice_id, name, audio_data)
VALUES ('default', 'June Default', pg_read_binary_file('/tmp/June.wav'));
"

# 6. VERIFY THE DATA
kubectl exec postgresql-0 -n june-services -- psql -U keycloak -d june -c "
SELECT voice_id, name, length(audio_data) as size_bytes, created_at FROM tts_voices;
"

# 7. CLEAN UP
kubectl exec postgresql-0 -n june-services -- rm /tmp/June.wav

# DONE
echo "✅ DONE! Database: june, Table: tts_voices"
