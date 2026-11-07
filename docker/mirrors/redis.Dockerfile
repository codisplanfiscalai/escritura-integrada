# syntax=docker/dockerfile:1.7.1
ARG UPSTREAM_IMAGE
FROM ${UPSTREAM_IMAGE}
ARG CONTENT_ID
ARG SOURCE_REVISION
LABEL org.opencontainers.image.title="Escritura Integrada — Redis opcional" \
      org.opencontainers.image.source="https://github.com/codisplanfiscalai/escritura-integrada" \
      org.opencontainers.image.revision=${SOURCE_REVISION} \
      io.escritura.content-id=${CONTENT_ID}
COPY --chmod=755 docker/mirrors/redis-entrypoint.sh /usr/local/bin/escritura-entrypoint
ENTRYPOINT ["/usr/local/bin/escritura-entrypoint"]
CMD ["redis-server"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 \
    CMD REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning ping | grep -q PONG
