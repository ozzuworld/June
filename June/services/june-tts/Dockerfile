# June/services/june-tts/Dockerfile - DIRECT CHATTERBOX (RECOMMENDED)
FROM travisvn/chatterbox-tts-api:latest

# Configure for your environment
ENV DEVICE=cpu \
    PORT=8080 \
    LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1 \
    # Chatterbox specific settings
    EXAGGERATION=0.5 \
    CFG_WEIGHT=0.5 \
    TEMPERATURE=1.0

# The image already includes everything needed
# Just expose the port and run
EXPOSE 8080

# Health check using Chatterbox's built-in endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Use the original entrypoint - don't override it
CMD ["python", "main.py"]