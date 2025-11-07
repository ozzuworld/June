FROM python:3.10-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN git clone https://github.com/ufal/whisper_streaming.git /tmp/whisper_streaming
RUN cp /tmp/whisper_streaming/whisper_online.py /app/ && \
    rm -rf /tmp/whisper_streaming

COPY main.py .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

CMD ["python", "main.py"]
