FROM quay.io/keycloak/keycloak:26.4.0

# Copy custom configuration if needed
# COPY keycloak.conf /opt/keycloak/conf/keycloak.conf

# Build optimized Keycloak with health endpoints enabled
# CRITICAL: Health and metrics must be enabled at BUILD time
RUN /opt/keycloak/bin/kc.sh build \
    --db=postgres \
    --health-enabled=true \
    --metrics-enabled=true

# Create non-root user
USER 1000

EXPOSE 8080 9000

# Use optimized startup
ENTRYPOINT ["/opt/keycloak/bin/kc.sh", "start", "--optimized"]