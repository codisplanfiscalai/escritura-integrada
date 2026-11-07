#!/bin/sh
set -eu
MINIO_ROOT_USER=${MINIO_ROOT_USER:-}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD:-}
if [ "${#MINIO_ROOT_USER}" -lt 3 ] || [ "${#MINIO_ROOT_PASSWORD}" -lt 16 ]; then
    echo 'Perfil minio: defina MINIO_ROOT_USER (mínimo 3) e MINIO_ROOT_PASSWORD (mínimo 16 caracteres) no .env.' >&2
    exit 64
fi
export MINIO_ROOT_USER MINIO_ROOT_PASSWORD
exec /usr/local/bin/minio "$@"
