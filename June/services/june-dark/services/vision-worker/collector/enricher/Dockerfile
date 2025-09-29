FROM python:3.11-slim

RUN apt-get update && apt-get install -y exiftool poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pandas==2.2.2 fastapi==0.114.0 uvicorn[standard]==0.30.6 \
    elasticsearch==8.14.0 minio==7.2.7 psycopg[binary,pool]==3.2.1 \
    pika==1.3.2 redis==5.0.8 trafilatura==1.8.1 pdfplumber==0.11.4

WORKDIR /app
COPY ./app /app
EXPOSE 9010
CMD ["uvicorn", "enricher:app", "--host", "0.0.0.0", "--port", "9010"]
