FROM quay.io/keycloak/keycloak:latest
COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Recommended at build time (safe defaults; can also be env at runtime)
ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_DB=postgres

# Don’t bake secrets into the image. Pass DB URL/USER/PASSWORD at deploy time.
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start"]  # Cloud Run: production, not start-dev
