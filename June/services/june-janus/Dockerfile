FROM sucwangsr/janus-webrtc-gateway-docker:latest

# Copy custom Janus configuration
COPY janus.jcfg /opt/janus/etc/janus/janus.jcfg

# Copy and make executable the entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Use our custom entrypoint
ENTRYPOINT ["/entrypoint.sh"]
