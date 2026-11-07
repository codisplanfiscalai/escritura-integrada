#!/bin/sh
set -eu
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD:-}
MYSQL_PASSWORD=${MYSQL_PASSWORD:-}
if [ "${#MYSQL_ROOT_PASSWORD}" -lt 16 ] || [ "${#MYSQL_PASSWORD}" -lt 16 ]; then
    echo 'Perfil mysql: defina MYSQL_ROOT_PASSWORD e MYSQL_PASSWORD com pelo menos 16 caracteres no .env.' >&2
    exit 64
fi
export MYSQL_ROOT_PASSWORD MYSQL_PASSWORD
exec /usr/local/bin/docker-entrypoint.sh "$@"
