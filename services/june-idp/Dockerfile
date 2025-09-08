# ====== Build stage ======
FROM quay.io/keycloak/keycloak:latest AS builder

# Enable health and metrics in the optimized runtime
ENV KC_HEALTH_ENABLED=true     KC_METRICS_ENABLED=true     KC_DB=postgres

WORKDIR /opt/keycloak

# Demo keystore (dev only). Replace with a proper cert/keystore in prod or remove.
RUN keytool -genkeypair     -storepass password -storetype PKCS12 -keyalg RSA -keysize 2048     -dname "CN=server" -alias server     -ext "SAN:c=DNS:localhost,IP:127.0.0.1"     -keystore conf/server.keystore

# Build the optimized Keycloak runtime (compiles providers, trims distro)
RUN /opt/keycloak/bin/kc.sh build

# ====== Final runtime stage ======
FROM quay.io/keycloak/keycloak:latest

# Copy the optimized runtime from builder
COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Safe defaults baked into the image (no secrets)
ENV KC_HEALTH_ENABLED=true     KC_METRICS_ENABLED=true     KC_DB=postgres

# Cloud Run will pass DB creds + hostname at runtime via env/args
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start"]
