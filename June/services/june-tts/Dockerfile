# FIXED: OpenVoice V2 Installation in Docker
# The issue was with editable installs (-e) not working properly in multi-stage Docker builds

# ============================================================================
# Production Stage - Install OpenVoice V2 DIRECTLY
# ============================================================================
FROM python:3.10-slim as production

# Install runtime and build dependencies (needed for OpenVoice)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libsndfile1 \
    mecab \
    mecab-ipadic-utf8 \
    ffmpeg \
    git \
    git-lfs \
    build-essential \
    pkg-config \
    libmecab-dev \
    && rm -rf /var/lib/apt/lists/*

# Initialize Git LFS
RUN git lfs install

# Copy the virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /workspace

# Copy application files
COPY requirements.txt /workspace/
COPY setup_nltk.py /workspace/
COPY model_setup.py /workspace/
COPY shared/ /workspace/shared/
COPY app/ /workspace/app/

# Install any additional requirements
RUN pip install --no-cache-dir -r requirements.txt

# CRITICAL FIX: Install OpenVoice V2 properly in production stage
RUN echo "📦 Installing OpenVoice V2 directly in production..." && \
    # Install MeCab dependencies first
    export MECAB_CONFIG=/usr/bin/mecab-config && \
    pip install --no-cache-dir fugashi[unidic-lite]==1.3.0 unidic-lite && \
    # Install tokenizers and transformers (pinned versions)
    export PIP_ONLY_BINARY=tokenizers && \
    pip install --no-cache-dir --no-build-isolation --only-binary=:all: tokenizers==0.13.3 && \
    pip install --no-cache-dir transformers==4.27.4 && \
    # Install OpenVoice dependencies first
    pip install --no-cache-dir \
        librosa>=0.10.0 \
        scipy>=1.9.0 \
        matplotlib>=3.5.0 \
        tqdm>=4.60.0 \
        monotonic_align>=0.1.2 \
        phonemizer>=3.2.0 \
        pypinyin>=0.50.0 \
        jieba>=0.42.1 \
        cn2an>=0.5.17 \
        inflect>=7.0.0 \
        unidecode>=1.3.7 && \
    # Clone and install OpenVoice (NOT in editable mode for Docker)
    cd /tmp && \
    git clone --depth 1 https://github.com/myshell-ai/OpenVoice.git && \
    cd OpenVoice && \
    # FIXED: Use regular install instead of editable (-e) for Docker
    pip install --no-cache-dir . && \
    # Verify installation immediately
    python -c "from openvoice.api import ToneColorConverter; print('✅ OpenVoice installed successfully')" && \
    python -c "from openvoice import se_extractor; print('✅ se_extractor available')" && \
    # Clean up
    cd / && rm -rf /tmp/OpenVoice

# Download unidic for Japanese support
RUN python -m unidic download || true

# Create model directories
RUN mkdir -p /models/openvoice/checkpoints_v2/base_speakers && \
    mkdir -p /models/openvoice/checkpoints_v2/tone_color_converter

# Run model setup (downloads OpenVoice V2 models)
RUN python /workspace/model_setup.py

# Run NLTK setup
RUN python /workspace/setup_nltk.py

# Create non-root user and set permissions
RUN useradd -m -u 1001 appuser && \
    mkdir -p /home/appuser/.cache/huggingface/hub && \
    mkdir -p /home/appuser/.cache/torch && \
    chown -R appuser:appuser /workspace /home/appuser /models

# Set environment variables
ENV HF_HOME=/home/appuser/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface
ENV TORCH_HOME=/home/appuser/.cache/torch
ENV OPENVOICE_CHECKPOINTS_V2=/models/openvoice/checkpoints_v2
ENV PYTHONPATH="/workspace:/workspace/shared"
ENV HOST=0.0.0.0
ENV PORT=8000
ENV MELO_LANGUAGE=EN
ENV MELO_SPEAKER_ID=0
ENV CORS_ALLOW_ORIGINS="*"

# Switch to non-root user
USER appuser

# FIXED: Comprehensive verification
RUN echo "🔍 Runtime verification:" && \
    python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}')" && \
    python -c "from melo.api import TTS; print('✅ MeloTTS imports OK')" && \
    python -c "from openvoice.api import ToneColorConverter; print('✅ OpenVoice ToneColorConverter OK')" && \
    python -c "from openvoice import se_extractor; print('✅ OpenVoice se_extractor OK')" && \
    python -c "import sys; print(f'Python packages: {len([p for p in sys.path if \"site-packages\" in p])} site-packages dirs')" && \
    echo "🎉 All components verified successfully!"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Expose port
EXPOSE 8000

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]