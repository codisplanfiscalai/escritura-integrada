# syntax=docker/dockerfile:1.7.1
ARG UPSTREAM_IMAGE
FROM ${UPSTREAM_IMAGE}
ARG CONTENT_ID
ARG SOURCE_REVISION
LABEL org.opencontainers.image.title="Escritura Integrada — MySQL opcional" \
      org.opencontainers.image.source="https://github.com/codisplanfiscalai/escritura-integrada" \
      org.opencontainers.image.revision=${SOURCE_REVISION} \
      io.escritura.content-id=${CONTENT_ID}
COPY --chmod=755 docker/mirrors/mysql-entrypoint.sh /usr/local/bin/escritura-entrypoint
ENTRYPOINT ["/usr/local/bin/escritura-entrypoint"]
CMD ["mysqld"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=8 \
    CMD MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqladmin --protocol=TCP --host=127.0.0.1 --user=root ping --silent
