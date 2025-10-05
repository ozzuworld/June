# Multi‑stage Dockerfile to build a lean June‑TTS image

# Stage 1 — builder: install build‑time dependencies and download models
FROM python:3.10-slim AS builder

# General environment settings
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install build tools and libraries required by MeloTTS and OpenVoice. These
# packages are removed in the final stage to keep the image small.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    mecab \
    mecab-ipadic-utf8 \
    ffmpeg \
    git \
    git-lfs \
    build-essential \
    pkg-config \
    libmecab-dev \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install

# Create and activate a virtual environment for Python packages
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Upgrade pip and install core dependencies from requirements.txt
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip wheel setuptools && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Install MeloTTS and OpenVoice V2. Cloning OpenVoice into /tmp ensures
# that build‑time artefacts do not pollute the final image.
RUN pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git && \
    cd /tmp && git clone --depth 1 https://github.com/myshell-ai/OpenVoice.git && \
    cd OpenVoice && pip install --no-cache-dir . && \
    rm -rf /tmp/OpenVoice

# Download unidic for Japanese support. The command may fail if the
# dictionary already exists; ignore errors.
RUN python -m unidic download || true

# Copy application source and any scripts needed to download models or
# prepare resources. These scripts should be idempotent.
WORKDIR /workspace
COPY app/ /workspace/app/
COPY shared/ /workspace/shared/
COPY model_setup.py /workspace/
COPY setup_nltk.py /workspace/

# Create model directories and run model setup to download OpenVoice
# checkpoints. Also run any additional setup scripts such as NLTK
# downloads if necessary. Remove temporary files afterwards.
RUN mkdir -p /models/openvoice/checkpoints_v2 && \
    python /workspace/model_setup.py && \
    python /workspace/setup_nltk.py


# Stage 2 — runtime: copy only what is needed to run the service
FROM python:3.10-slim

# Environment settings for runtime
ENV PYTHONUNBUFFERED=1

# Install runtime libraries only (no compilers). These packages are required
# at runtime by soundfile and the TTS models.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    mecab \
    mecab-ipadic-utf8 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre‑built virtual environment and application from the builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY --from=builder /workspace/app /workspace/app
COPY --from=builder /workspace/shared /workspace/shared
COPY --from=builder /models /models

# Set working directory
WORKDIR /workspace

# Create a non‑root user to run the service and adjust permissions
RUN useradd -m -u 1001 appuser && \
    chown -R appuser:appuser /workspace /models

# Switch to the non‑root user
USER appuser

# Expose the port used by Uvicorn
EXPOSE 8000

# Start the FastAPI application. Uvicorn will use a single worker to
# minimise memory usage; adjust as needed for your deployment.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]