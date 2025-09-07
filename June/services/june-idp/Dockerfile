# June/services/keycloak/Dockerfile
FROM quay.io/keycloak/keycloak:26.0.5 AS builder

# Enable health/metrics and pick Postgres
ENV KC_HEALTH_ENABLED=true
ENV KC_METRICS_ENABLED=true
ENV KC_DB=postgres

# Pre-optimize (faster cold starts)
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.0.5
COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Start in production; Cloud Run will pass PORT=8080 and sit in front as TLS proxy
# We enable HTTP and trust proxy headers; hostname comes from env at deploy
ENTRYPOINT ["/opt/keycloak/bin/kc.sh", "start", "--optimized"]
