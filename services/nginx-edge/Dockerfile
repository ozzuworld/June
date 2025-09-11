FROM nginx:1.27-alpine

# Remove default site so only our server block is active
RUN rm -f /etc/nginx/conf.d/default.conf

# Drop our conf.d file (included inside http {})
COPY edge.conf /etc/nginx/conf.d/edge.conf

# Validate at build to catch syntax errors early
RUN nginx -t

EXPOSE 8080
CMD ["sh","-c","nginx -T && exec nginx -g 'daemon off;'"]
