# syntax=docker/dockerfile:1.7.1
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE} AS base
ARG CONTENT_ID
ARG SOURCE_REVISION
ARG SOURCE_URL=https://github.com/codisplanfiscalai/escritura-integrada
LABEL org.opencontainers.image.title="Escritura Integrada — base Python" \
      org.opencontainers.image.source=${SOURCE_URL} \
      org.opencontainers.image.revision=${SOURCE_REVISION} \
      org.opencontainers.image.version=${CONTENT_ID} \
      io.escritura.content-id=${CONTENT_ID}
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ESCRITURA_DATA_DIR=/data \
    ESCRITURA_DEMO=0
RUN apt-get update && apt-get install -y --no-install-recommends libarchive-tools=3.6.2-1+deb12u5 libarchive13=3.6.2-1+deb12u5 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY docker/runtime.lock /usr/share/escritura/runtime.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=secret,id=proxy_ca \
    if [ -s /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip install --only-binary=:all: --require-hashes --no-deps -r /usr/share/escritura/runtime.lock \
    && python -m pip check
RUN groupadd --gid 10001 escritura \
    && useradd --uid 10001 --gid escritura --no-create-home --shell /usr/sbin/nologin escritura \
    && mkdir -p /data && chown escritura:escritura /data
USER 10001:10001
VOLUME ["/data"]
CMD ["python", "--version"]
