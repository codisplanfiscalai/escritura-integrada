#!/bin/sh
set -eu
REDIS_PASSWORD=${REDIS_PASSWORD:-}
if [ "${#REDIS_PASSWORD}" -lt 16 ]; then
    echo 'Perfil redis: defina REDIS_PASSWORD com pelo menos 16 caracteres no .env.' >&2
    exit 64
fi
if [ "$1" = 'redis-server' ]; then
    shift
    exec /usr/local/bin/docker-entrypoint.sh redis-server --appendonly yes --protected-mode yes --requirepass "$REDIS_PASSWORD" "$@"
fi
exec /usr/local/bin/docker-entrypoint.sh "$@"
