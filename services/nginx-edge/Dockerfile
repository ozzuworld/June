FROM nginx:1.27-alpine

# Only our server should be active
RUN rm -f /etc/nginx/conf.d/default.conf

# Drop our conf.d file (included inside http {})
COPY edge.conf /etc/nginx/conf.d/edge.conf

# Validate at build
RUN nginx -t

EXPOSE 8080
# Print effective config on startup (helps verify health block is present)
CMD ["sh","-c","nginx -T && exec nginx -g 'daemon off;'"]
