# syntax=docker/dockerfile:1.7.1
ARG UPSTREAM_IMAGE
FROM ${UPSTREAM_IMAGE}
ARG CONTENT_ID
ARG SOURCE_REVISION
LABEL org.opencontainers.image.title="Escritura Integrada — PostgreSQL opcional" \
      org.opencontainers.image.source="https://github.com/codisplanfiscalai/escritura-integrada" \
      org.opencontainers.image.revision=${SOURCE_REVISION} \
      io.escritura.content-id=${CONTENT_ID}
COPY --chmod=755 docker/mirrors/postgres-entrypoint.sh /usr/local/bin/escritura-entrypoint
ENTRYPOINT ["/usr/local/bin/escritura-entrypoint"]
CMD ["postgres"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"
