FROM sucwangsr/janus-webrtc-gateway-docker:latest

# Install netcat for connectivity testing
USER root
RUN apt-get update && apt-get install -y netcat-openbsd && rm -rf /var/lib/apt/lists/*

# Create necessary directories
RUN mkdir -p /usr/local/etc/janus/

# Copy custom Janus configuration with fixed paths
COPY janus.jcfg /usr/local/etc/janus/janus.jcfg

# Copy and make executable the entrypoint script  
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Ensure proper permissions
RUN chown -R www-data:www-data /usr/local/etc/janus/

# Expose necessary ports
EXPOSE 8088 8188 8089 7088

# Use our custom entrypoint
ENTRYPOINT ["/entrypoint.sh"]
