FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && addgroup --system app \
 && adduser --system --ingroup app app

# Add code (env comes from Cloud Run/Secret Manager, not local files)
COPY app ./app

RUN chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "${PORT:-8080}"]
