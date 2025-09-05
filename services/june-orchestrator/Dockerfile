# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && addgroup --system app \
 && adduser --system --ingroup app app

COPY . .

RUN chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["sh","-c","uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --ws websockets"]
