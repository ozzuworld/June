# Use the reliable Software Mansion Janus Gateway image
FROM swmansion/janus-gateway:0.14.4-0

# Environment variables for configuration
ENV GATEWAY_IP=0.0.0.0
ENV WEBSOCKETS_ENABLED=true
ENV HTTP_ENABLED=true
ENV RTP_PORT_RANGE=10000-10200
ENV ADMIN_KEY=janusoverlord
ENV API_SECRET=janussecret

# Create necessary directories
USER root
RUN mkdir -p /opt/janus/etc/janus

# Expose standard Janus ports
EXPOSE 8088 8188 8089 7088 10000-10200/udp

# Health check using the info endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8088/janus/info || exit 1

# Use the default entrypoint from swmansion image
# This image handles configuration via environment variables