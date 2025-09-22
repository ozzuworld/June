# services/june-idp/Dockerfile
# Custom Keycloak image with June AI Platform branding and configuration

FROM quay.io/keycloak/keycloak:23.0.3 as builder

# Enable health and metrics support
ENV KC_HEALTH_ENABLED=true
ENV KC_METRICS_ENABLED=true

# Configure built-in database for development (use external DB for production)
ENV KC_DB=h2

# Build the optimized Keycloak
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:23.0.3

# Copy the built Keycloak
COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Create directory for realm imports
RUN mkdir -p /opt/keycloak/data/import

# Copy custom themes (if you have any)
# COPY themes/ /opt/keycloak/themes/

# Set environment variables
ENV KEYCLOAK_ADMIN=admin
ENV KEYCLOAK_ADMIN_PASSWORD=Pokemon123!
ENV KC_HOSTNAME_STRICT=false
ENV KC_HOSTNAME_STRICT_HTTPS=false
ENV KC_HTTP_ENABLED=true
ENV KC_PROXY=edge

# Expose port
EXPOSE 8080

# Use non-root user
USER 1000

# Entry point
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]