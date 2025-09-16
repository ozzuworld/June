# June/services/june-tts/Dockerfile - PRODUCTION
FROM travisvn/chatterbox-tts-api:latest as chatterbox

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    nginx \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Chatterbox API from first stage
COPY --from=chatterbox /app /chatterbox
COPY --from=chatterbox /root/.cache/huggingface /root/.cache/huggingface

# Install Chatterbox requirements
WORKDIR /chatterbox
RUN pip install --no-cache-dir -r requirements.txt

# Install June TTS requirements
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy June TTS application
COPY . .

# Create supervisor configuration
RUN mkdir -p /var/log/supervisor

COPY <<EOF /etc/supervisor/conf.d/supervisord.conf
[supervisord]
nodaemon=true
user=root

[program:chatterbox]
command=python /chatterbox/main.py
directory=/chatterbox
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
environment=DEVICE="cpu",PORT="8000",LOG_LEVEL="INFO"

[program:june-tts]
command=python /app/app.py
directory=/app
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
environment=PORT="8080",CHATTERBOX_API_URL="http://localhost:8000"

[program:nginx]
command=/usr/sbin/nginx -g "daemon off;"
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

# Nginx configuration for internal routing
COPY <<EOF /etc/nginx/sites-enabled/default
server {
    listen 8080;
    
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    
    location /health {
        access_log off;
        return 200 "OK";
    }
}
EOF

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]