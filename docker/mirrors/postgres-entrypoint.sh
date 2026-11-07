#!/bin/sh
set -eu
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-}
if [ "${#POSTGRES_PASSWORD}" -lt 16 ]; then
    echo 'Perfil postgres: defina POSTGRES_PASSWORD com pelo menos 16 caracteres no .env.' >&2
    exit 64
fi
export POSTGRES_PASSWORD
exec /usr/local/bin/docker-entrypoint.sh "$@"
