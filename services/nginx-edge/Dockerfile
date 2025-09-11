# June/services/nginx-edge/Dockerfile
FROM nginx:1.27-alpine

# We no longer need gettext/envsubst since the entrypoint builds nginx.conf directly
RUN apk add --no-cache bash curl

# Bring in the dynamic entrypoint
COPY nginx.conf.fixed /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
