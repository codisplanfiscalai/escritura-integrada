# syntax=docker/dockerfile:1.7.1
ARG NODE_IMAGE
ARG RUNTIME_IMAGE
FROM ${NODE_IMAGE} AS interface
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    --mount=type=secret,id=proxy_ca \
    if [ -s /run/secrets/proxy_ca ]; then \
      NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca npm ci; \
    else npm ci; fi
COPY frontend/index.html frontend/vite.config.js ./
COPY frontend/public/ ./public/
COPY frontend/src/ ./src/
COPY frontend/scripts/ ./scripts/
RUN npm run build

FROM ${RUNTIME_IMAGE} AS reception-runtime
# Metadata copied into a new named volume by Docker. No key is built into images.
USER 0:0
RUN mkdir -p /run/escritura/reception-vault \
    && chown 10001:10001 /run/escritura/reception-vault \
    && chmod 0700 /run/escritura/reception-vault
COPY docker/postgres.lock /usr/share/escritura/postgres.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=secret,id=proxy_ca \
    if [ -s /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip install --only-binary=:all: --require-hashes --no-deps -r /usr/share/escritura/postgres.lock \
    && python -m pip check
USER 10001:10001

FROM reception-runtime AS app
ARG APP_VERSION
ARG SOURCE_REVISION
ARG CONTENT_ID
ARG SOURCE_URL=https://github.com/codisplanfiscalai/escritura-integrada
LABEL org.opencontainers.image.title="Escritura Integrada" \
      org.opencontainers.image.description="Aplicativo fiscal, contábil e financeiro; PostgreSQL operacional e SQLite desktop" \
      org.opencontainers.image.source=${SOURCE_URL} \
      org.opencontainers.image.revision=${SOURCE_REVISION} \
      org.opencontainers.image.version=${APP_VERSION} \
      io.escritura.content-id=${CONTENT_ID}
WORKDIR /app
COPY --chown=root:root app/ ./app/
COPY --chown=root:root scripts/run_container.py ./scripts/run_container.py
COPY --chown=root:root VERSION ./VERSION
COPY --from=interface --chown=root:root /frontend/dist/ ./frontend/dist/
USER 0:0
RUN chmod -R a+rX /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)); assert r.get('status') == 'ok'"]
CMD ["python", "scripts/run_container.py"]
