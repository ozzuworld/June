FROM python:3.11-slim

RUN pip install --no-cache-dir fastapi==0.114.0 uvicorn[standard]==0.30.6 \
    pydantic==2.8.2 httpx==0.27.2 elasticsearch==8.14.0 \
    neo4j==5.23.1 psycopg[binary,pool]==3.2.1 redis==5.0.8 \
    minio==7.2.7 tenacity==9.0.0

WORKDIR /app
COPY ./app /app
EXPOSE 8080
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
