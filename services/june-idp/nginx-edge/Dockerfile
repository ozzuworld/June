FROM nginx:1.27-alpine

# runtime deps for envsubst + curl (for health)
RUN apk add --no-cache bash curl gettext

# template + entrypoint
COPY nginx.conf.template /etc/nginx/templates/nginx.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# simple liveness check script (optional)
COPY /dev/null /usr/share/nginx/html/healthz

ENV NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx
ENV NGINX_ENVSUBST_TEMPLATE_DIR=/etc/nginx/templates

# Cloud Run provides PORT; we also require UPSTREAM_URL
# Example: UPSTREAM_URL=https://<keycloak-cloud-run-hostname>
ENV PORT=8080

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
