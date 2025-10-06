FROM python:3.9-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps that OpenVoice needs
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Official OpenVoice installation method
RUN git clone https://github.com/myshell-ai/OpenVoice.git && \
    cd OpenVoice && \
    pip install -e .

# Install MeloTTS (required for V2)
RUN pip install git+https://github.com/myshell-ai/MeloTTS.git

# Download unidic for Japanese support
RUN python -m unidic download

# Your app requirements
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy your app
COPY . /workspace

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
