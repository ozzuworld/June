FROM sucwangsr/janus-webrtc-gateway-docker:latest

# The image already has proper Janus 1.3.2+ setup
# Just expose the standard ports
EXPOSE 8088 8188 8089 7088

# Health check using the standard endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8088/janus/info || exit 1

# Use the default entrypoint from the image