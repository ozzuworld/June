# services/nginx-edge/Dockerfile
FROM nginx:1.27-alpine

# Keep it simple: no envsubst/template dance
RUN rm -f /etc/nginx/conf.d/default.conf

# Copy trimmed config directly into place
COPY nginx.conf.fixed /etc/nginx/nginx.conf

EXPOSE 8080
CMD ["nginx","-g","daemon off;"]
