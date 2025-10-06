FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Create cache directories  
RUN mkdir -p /tmp/nltk_data /nltk_data && chmod 777 /tmp/nltk_data /nltk_data

# Set environment variables
ENV NLTK_DATA=/tmp/nltk_data \
    TRANSFORMERS_CACHE=/tmp/transformers \
    HF_HOME=/tmp/huggingface

# Install OpenVoice
RUN git clone https://github.com/myshell-ai/OpenVoice.git . && \
    pip install --no-cache-dir -e . && \
    python -c "import nltk; nltk.download('averaged_perceptron_tagger')" || true

# Install your app requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your app
COPY . /workspace/app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
