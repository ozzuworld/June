# services/june-idp/Dockerfile
# STREAMLINED - Completely disable clustering for Cloud Run

FROM quay.io/keycloak/keycloak:latest AS builder

ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_DB=postgres

WORKDIR /opt/keycloak
RUN /opt/keycloak/bin/kc.sh build --cache=local

FROM quay.io/keycloak/keycloak:latest

COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Completely disable clustering at JVM level
ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_DB=postgres \
    KC_HTTP_ENABLED=true \
    KC_HOSTNAME_STRICT=false \
    KC_TRANSACTION_XA_ENABLED=false \
    KC_CACHE=local \
    JAVA_OPTS_APPEND="-Djgroups.tcp.address=127.0.0.1 -Djava.net.preferIPv4Stack=true -Dkeycloak.connectionsInfinispan.default.clustered=false"

ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--http-enabled=true", "--hostname-strict=false", "--proxy-headers=xforwarded", "--db=postgres", "--transaction-xa-enabled=false", "--cache=local"]