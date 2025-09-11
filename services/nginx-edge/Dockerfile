# services/nginx-edge/Dockerfile
FROM nginx:1.27-alpine
RUN apk add --no-cache bash curl
COPY nginx.conf.fixed /etc/nginx/nginx.conf
ENV PORT=8080
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
