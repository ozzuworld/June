FROM quay.io/keycloak/keycloak:latest

# Set environment variables
ENV KC_DB=postgres
ENV KC_HEALTH_ENABLED=true
ENV KC_METRICS_ENABLED=true
ENV KC_FEATURES=token-exchange

# Build the optimized Keycloak image
RUN /opt/keycloak/bin/kc.sh build

# Set the entrypoint
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
# Use development mode for easier setup
CMD ["start-dev"]
