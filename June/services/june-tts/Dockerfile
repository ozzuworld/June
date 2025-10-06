FROM python:3.9-slim

# Install system dependencies (both OpenVoice and MeloTTS need these)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Create necessary directories
RUN mkdir -p /workspace/models /workspace/app

# Install OpenVoice first (with dependencies)
RUN git clone https://github.com/myshell-ai/OpenVoice.git /workspace/OpenVoice && \
    cd /workspace/OpenVoice && \
    pip install --no-cache-dir -e .

# Install MeloTTS (avoiding conflicts)
RUN pip install --no-cache-dir \
    "mecab-python3>=1.0.6" \
    "unidic-lite>=1.0.8" \
    "num2words" \
    && pip install --no-cache-dir git+https://github.com/myshell-ai/MeloTTS.git

# Download NLTK data and unidic (required for multilingual)
RUN python -c "import nltk; nltk.download('averaged_perceptron_tagger')" || true
RUN python -m unidic download || true

# Install your app requirements  
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your app to the correct location
COPY . /workspace/app

# Set Python path so imports work
ENV PYTHONPATH="/workspace:/workspace/OpenVoice:${PYTHONPATH}"

WORKDIR /workspace/app

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
