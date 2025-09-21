FROM quay.io/keycloak/keycloak:26.3.4

ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true

USER root
ADD https://repo1.maven.org/maven2/com/oracle/database/jdbc/ojdbc17/23.9.0.25.07/ojdbc17-23.9.0.25.07.jar /opt/keycloak/providers/ojdbc17.jar
ADD https://repo1.maven.org/maven2/com/oracle/database/nls/orai18n/23.6.0.24.10/orai18n-23.6.0.24.10.jar /opt/keycloak/providers/orai18n.jar
USER keycloak

# 👇 this pins the build-time vendor – no runtime mismatch
RUN /opt/keycloak/bin/kc.sh build --db=oracle

ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start","--optimized"]
