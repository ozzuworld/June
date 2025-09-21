# June/services/june-idp/Dockerfile
# FIXED: Keycloak built specifically for Oracle database

FROM quay.io/keycloak/keycloak:23.0.0 AS builder

# Set Oracle as the database type at BUILD time (this fixes the error)
ENV KC_DB=oracle \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_HTTP_ENABLED=true \
    KC_TRANSACTION_XA_ENABLED=false

WORKDIR /opt/keycloak

# CRITICAL: Build Keycloak with Oracle support
# This ensures the database type is properly set at build time
RUN /opt/keycloak/bin/kc.sh build --db=oracle

# ============================================
# Runtime stage with Oracle configuration
# ============================================
FROM quay.io/keycloak/keycloak:23.0.0

# Copy the built Keycloak with Oracle support
COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Runtime environment for Oracle
ENV KC_DB=oracle \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_HTTP_ENABLED=true \
    KC_HOSTNAME_STRICT=false \
    KC_TRANSACTION_XA_ENABLED=false \
    KC_CACHE=local \
    KC_PROXY=edge \
    # Oracle specific environment
    TNS_ADMIN=/opt/oracle/wallet \
    ORACLE_HOME=/opt/oracle \
    # JVM tuning for Oracle connections
    JAVA_OPTS_APPEND="-Djava.net.preferIPv4Stack=true -Duser.timezone=UTC -Doracle.jdbc.fanEnabled=false"

# Create Oracle directory structure
USER root
RUN mkdir -p /opt/oracle/wallet && \
    chmod 755 /opt/oracle && \
    chmod 755 /opt/oracle/wallet

# Switch back to keycloak user
USER 1000

WORKDIR /opt/keycloak

ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]

# Start with Oracle-specific configuration
CMD ["start", \
     "--db=oracle", \
     "--http-enabled=true", \
     "--hostname-strict=false", \
     "--proxy=edge", \
     "--transaction-xa-enabled=false", \
     "--cache=local", \
     "--health-enabled=true", \
     "--metrics-enabled=true"]