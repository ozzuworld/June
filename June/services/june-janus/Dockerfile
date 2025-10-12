FROM canyan/janus-gateway:latest

# Copy Janus configuration files
COPY janus-config/*.jcfg /opt/janus/etc/janus/

# Expose ports
EXPOSE 8088 8188 8089 7088

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8088/janus/info || exit 1

# Start Janus
CMD ["/opt/janus/bin/janus", "-F", "/opt/janus/etc/janus"]