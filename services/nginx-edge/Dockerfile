FROM nginx:1.27-alpine

# Only our server should be active
RUN rm -f /etc/nginx/conf.d/default.conf

# IMPORTANT: this must match the file you just created
COPY edge.conf /etc/nginx/conf.d/edge.conf

# Validate at build time (fails fast on syntax issues)
RUN nginx -t

EXPOSE 8080
# Print effective config at startup so you can SEE what's loaded in Cloud Run logs
CMD ["sh","-c","nginx -T; exec nginx -g 'daemon off;'"]
