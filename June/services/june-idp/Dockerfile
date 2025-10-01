FROM quay.io/keycloak/keycloak:26.4.0

# Copy custom configuration
COPY keycloak.conf /opt/keycloak/conf/keycloak.conf

# Build optimized Keycloak for production
RUN /opt/keycloak/bin/kc.sh build --db=postgres

# Create non-root user
USER 1000

EXPOSE 8080 9000

# Use optimized startup
ENTRYPOINT ["/opt/keycloak/bin/kc.sh", "start", "--optimized"]
