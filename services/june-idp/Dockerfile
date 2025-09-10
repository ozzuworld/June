# services/june-idp/Dockerfile
# Fixed version that COMPLETELY disables clustering for Cloud Run

# ====== Build stage ======
FROM quay.io/keycloak/keycloak:latest AS builder

ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_DB=postgres

WORKDIR /opt/keycloak

# Build WITHOUT any cache (completely disable Infinispan)
RUN /opt/keycloak/bin/kc.sh build \
    --cache=local

# ====== Final runtime stage ======
FROM quay.io/keycloak/keycloak:latest

# Copy from the named build stage
COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Environment variables to disable clustering completely
ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_DB=postgres \
    KC_HTTP_ENABLED=true \
    KC_HOSTNAME_STRICT=false \
    KC_TRANSACTION_XA_ENABLED=false \
    KC_CACHE=local \
    JAVA_OPTS_APPEND="-Djgroups.tcp.address=NON_LOOPBACK -Djava.net.preferIPv4Stack=true -Djgroups.bind_addr=127.0.0.1"

ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]

# Critical: Start with single-node configuration and JGroups override
CMD ["start", "--http-enabled=true", "--hostname-strict=false", "--proxy-headers=xforwarded", "--db=postgres", "--transaction-xa-enabled=false", "--cache=local"]