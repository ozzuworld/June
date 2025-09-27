# Simple June TTS Dockerfile - Avoiding inline Python issues
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MODEL_ID=myshell-ai/OpenVoiceV2
ENV OPENVOICE_CHECKPOINTS_V2=/models/openvoice/checkpoints_v2
ENV VENV_DIR=/opt/openvoice/venv
ENV OPENVOICE_SRC_DIR=/opt/openvoice/OpenVoice
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    unzip \
    wget \
    curl \
    libsndfile1 \
    tree \
    pkg-config \
    mecab \
    libmecab-dev \
    mecab-ipadic-utf8 \
    mecab-utils \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python3.10 -m venv $VENV_DIR

# Install PyTorch (CPU version for compatibility)
RUN $VENV_DIR/bin/pip install --upgrade pip wheel setuptools
RUN $VENV_DIR/bin/pip install "torch>=2.3" --index-url https://download.pytorch.org/whl/cpu

# Install core dependencies
RUN $VENV_DIR/bin/pip install fastapi "uvicorn[standard]" httpx soundfile numpy huggingface_hub

# Install MeCab + fugashi
ENV MECAB_CONFIG=/usr/bin/mecab-config
RUN $VENV_DIR/bin/pip install --no-cache-dir 'fugashi[unidic-lite]==1.3.0' 'unidic-lite<1.1.0'

# Test fugashi
RUN $VENV_DIR/bin/python -c "import fugashi; print('fugashi OK')"

# Install tokenizers (prebuilt wheel)
ENV PIP_ONLY_BINARY=tokenizers
RUN $VENV_DIR/bin/pip install --no-build-isolation --only-binary=:all: 'tokenizers==0.13.3'
RUN $VENV_DIR/bin/pip install 'transformers==4.27.4'

# Install MeloTTS
RUN $VENV_DIR/bin/pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Try unidic download (optional)
RUN $VENV_DIR/bin/python -c "import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'unidic', 'download'])" || true

# Clone and install OpenVoice
RUN rm -rf $OPENVOICE_SRC_DIR
RUN git clone https://github.com/myshell-ai/OpenVoice.git $OPENVOICE_SRC_DIR
RUN $VENV_DIR/bin/pip install -e $OPENVOICE_SRC_DIR

# Create model directories
RUN mkdir -p $OPENVOICE_CHECKPOINTS_V2/base_speakers
RUN mkdir -p $OPENVOICE_CHECKPOINTS_V2/tone_color_converter

# Set working directory
WORKDIR /workspace

# Copy shared module and install
COPY shared/ /workspace/shared/
RUN $VENV_DIR/bin/pip install -e /workspace/shared/

# Install additional TTS requirements
COPY requirements.txt /workspace/
RUN $VENV_DIR/bin/pip install --no-cache-dir -r requirements.txt

# Copy the model download script
COPY model_setup.py /workspace/
RUN $VENV_DIR/bin/python /workspace/model_setup.py

# Copy application files
COPY app/ /workspace/app/

# Set runtime environment
ENV PYTHONPATH="/workspace:/workspace/shared"
ENV PATH="$VENV_DIR/bin:$PATH"
ENV HOST=0.0.0.0
ENV PORT=8000
ENV MELO_LANGUAGE=EN
ENV MELO_SPEAKER_ID=0
ENV CORS_ALLOW_ORIGINS="*"

# Verify final layout
RUN echo "Verifying model directory structure:" && \
    ls -la $OPENVOICE_CHECKPOINTS_V2/tone_color_converter/ || true

# Create non-root user
RUN groupadd -r appuser && \
    useradd -r -g appuser appuser && \
    chown -R appuser:appuser /workspace /models /opt/openvoice

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Expose port
EXPOSE 8000

# Switch to non-root user
USER appuser

# Start the application
CMD ["/opt/openvoice/venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]