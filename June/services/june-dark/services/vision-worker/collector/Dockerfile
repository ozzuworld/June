FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

RUN pip install --no-cache-dir scrapy==2.11.2 playwright==1.47.0 \
    httpx==0.27.2 requests==2.32.3 redis==5.0.8 pika==1.3.2 \
    beautifulsoup4==4.12.3 trafilatura==1.8.1

# Install browser deps (already present in base), ensure playwright browsers:
RUN playwright install --with-deps chromium

WORKDIR /crawler
COPY ./app /crawler
CMD ["python", "-m", "collector.entry"]
