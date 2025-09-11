FROM nginx:1.27-alpine

# Remove default site to avoid conflicts
RUN rm -f /etc/nginx/conf.d/default.conf

# Copy clean config and validate at build
COPY nginx.conf /etc/nginx/nginx.conf
RUN nginx -t

EXPOSE 8080
# Validate again at runtime (helps in Cloud Run logs), then run
CMD ["sh","-c","nginx -t && exec nginx -g 'daemon off;'"]
