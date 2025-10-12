# Dockerfile
FROM sucwangsr/janus-webrtc-gateway-docker:latest

# Copy custom Janus configuration that reads environment variables
COPY janus.jcfg /opt/janus/etc/janus/janus.jcfg

# Create startup script that substitutes environment variables
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
