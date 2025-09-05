FROM python:3.11-slim

# Install ffmpeg for on-the-fly audio conversion
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app \
    && adduser --system --ingroup app app

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

RUN chown -R app:app /app
USER app

# Cloud Run listens on $PORT (default 8080). We can hardcode 8080 safely.
EXPOSE 8080

# Start FastAPI app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
