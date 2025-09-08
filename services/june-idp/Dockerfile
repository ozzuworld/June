# ====== Build stage ======
FROM quay.io/keycloak/keycloak:latest AS builder

# Optional but nice defaults
ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_DB=postgres

WORKDIR /opt/keycloak

# (Optional) demo keystore for dev – remove/replace in prod
RUN keytool -genkeypair \
    -storepass password -storetype PKCS12 -keyalg RSA -keysize 2048 \
    -dname "CN=server" -alias server \
    -ext "SAN:c=DNS:localhost,IP:127.0.0.1" \
    -keystore conf/server.keystore

# Build the optimized runtime (compiles providers, trims distro)
RUN /opt/keycloak/bin/kc.sh build

# ====== Final runtime stage ======
FROM quay.io/keycloak/keycloak:latest

# Copy the optimized runtime from the builder stage
COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Safe defaults (no secrets baked)
ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_DB=postgres

ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start"]
