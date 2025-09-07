# jobs/pg-backup/Dockerfile
FROM postgres:16-alpine
RUN apk add --no-cache python3 py3-pip && pip3 install awscli
COPY backup.sh /backup.sh
RUN chmod +x /backup.sh
ENTRYPOINT ["/backup.sh"]
