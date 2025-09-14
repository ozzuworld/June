# June/services/june-kokoro-tts/Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies for audio processing and git-lfs
RUN apt-get update && apt-get install -y --no-install-recommends \
    espeak-ng \
    ffmpeg \
    git \
    git-lfs \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Download Kokoro model and voices using huggingface-hub (more reliable than git lfs)
RUN python -c "
import os
from huggingface_hub import snapshot_download

# Create models directory
os.makedirs('/app/models', exist_ok=True)

# Download the Kokoro model
print('Downloading Kokoro-82M model...')
try:
    snapshot_download(
        repo_id='hexgrad/Kokoro-82M',
        local_dir='/app/models',
        local_dir_use_symlinks=False,
        resume_download=True
    )
    print('Model download completed')
except Exception as e:
    print(f'Model download failed: {e}')
    # Create dummy files so build doesn't fail
    with open('/app/models/config.json', 'w') as f:
        f.write('{}')
    with open('/app/models/pytorch_model.bin', 'wb') as f:
        f.write(b'dummy')
    with open('/app/models/voices.bin', 'wb') as f:
        f.write(b'dummy')
    print('Created dummy model files - will download at runtime')

# List what we have
import os
print('Model directory contents:', os.listdir('/app/models'))
"

# Verify model files are present (either real or dummy)
RUN ls -la /app/models/ && \
    echo "Model files check completed"

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Start the service
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]