# ====== Build stage ======
FROM quay.io/keycloak/keycloak:latest AS builder

ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_DB=postgres

WORKDIR /opt/keycloak

# Build the optimized runtime (compiles providers, trims distro)
RUN /opt/keycloak/bin/kc.sh build

# ====== Final runtime stage ======
FROM quay.io/keycloak/keycloak:latest

# Copy from the named build stage
COPY --from=builder /opt/keycloak/ /opt/keycloak/

ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_DB=postgres \
    KC_HTTP_ENABLED=true \
    KC_HOSTNAME_STRICT=false \
    KC_TRANSACTION_XA_ENABLED=false

ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]

# Critical: Start with database-friendly settings and proper binding
CMD ["start", "--http-enabled=true", "--hostname-strict=false", "--proxy-headers=xforwarded", "--db=postgres", "--transaction-xa-enabled=false"]