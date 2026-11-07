# syntax=docker/dockerfile:1.7.1
ARG GOLANG_IMAGE
ARG RUNTIME_IMAGE
FROM ${GOLANG_IMAGE} AS builder
ARG MINIO_SOURCE_URL
ARG MINIO_SOURCE_SHA256
ARG MINIO_COMMIT
ARG MINIO_VERSION
ADD --checksum=${MINIO_SOURCE_SHA256} ${MINIO_SOURCE_URL} /tmp/minio-source.tar.gz
RUN mkdir -p /src && tar -xzf /tmp/minio-source.tar.gz --strip-components=1 -C /src
WORKDIR /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOFLAGS=-p=2
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod download && go mod verify \
    && go build -tags kqueue -trimpath -buildvcs=false \
       -ldflags="-s -w -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z -X github.com/minio/minio/cmd.ReleaseTag=${MINIO_VERSION} -X github.com/minio/minio/cmd.CommitID=${MINIO_COMMIT} -X github.com/minio/minio/cmd.ShortCommitID=9e49d5e7a648 -X github.com/minio/minio/cmd.CopyrightYear=2025" \
       -o /out/minio .

FROM ${RUNTIME_IMAGE}
ARG CONTENT_ID
ARG SOURCE_REVISION
ARG MINIO_COMMIT
ARG MINIO_VERSION
LABEL org.opencontainers.image.title="Escritura Integrada — MinIO compilado do fonte oficial" \
      org.opencontainers.image.source="https://github.com/codisplanfiscalai/escritura-integrada" \
      org.opencontainers.image.revision=${SOURCE_REVISION} \
      org.opencontainers.image.version=${MINIO_VERSION} \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      io.escritura.content-id=${CONTENT_ID} \
      io.escritura.upstream-commit=${MINIO_COMMIT}
COPY --from=builder /out/minio /usr/local/bin/minio
COPY --from=builder /src/LICENSE /usr/share/licenses/minio/LICENSE
COPY --from=builder /tmp/minio-source.tar.gz /usr/share/minio-source/source.tar.gz
COPY --chmod=755 docker/minio-entrypoint.sh /usr/local/bin/escritura-entrypoint
USER 10001:10001
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/escritura-entrypoint"]
CMD ["server", "/data", "--address", ":9000", "--console-address", ":9001"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:9000/minio/health/live',timeout=3).status == 200"]
