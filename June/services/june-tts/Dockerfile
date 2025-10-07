FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git build-essential && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

WORKDIR /workspace

# Create cache directories
RUN mkdir -p /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models && \
    chmod 777 /tmp/transformers /tmp/huggingface /tmp/nltk_data /cache /models

# Set environment variables
ENV TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface \
    NLTK_DATA=/tmp/nltk_data \
    PYTHONPATH="/workspace:/workspace/OpenVoice:${PYTHONPATH}"

# Install packages in batches with cleanup
RUN pip install --no-cache-dir torch==2.0.1 torchaudio==2.0.2 numpy==1.24.3 && \
    pip cache purge

RUN pip install --no-cache-dir \
    fastapi==0.104.1 uvicorn[standard]==0.24.0 pydantic==2.5.0 && \
    pip cache purge

RUN pip install --no-cache-dir \
    librosa==0.9.1 soundfile tqdm scipy resampy huggingface_hub && \
    pip cache purge

# Install MeloTTS with cleanup
RUN pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git && \
    pip cache purge

# Install OpenVoice
RUN git clone https://github.com/myshell-ai/OpenVoice.git /workspace/OpenVoice && \
    cd /workspace/OpenVoice && \
    pip install --no-cache-dir -e . --no-deps && \
    pip cache purge

# Copy app and setup
COPY . /workspace
RUN python setup_nltk.py && \
    python model_setup.py || echo "Model setup completed with warnings"

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
