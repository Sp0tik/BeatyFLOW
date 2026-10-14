#!/bin/sh
set -eu
mkdir -p backups
docker compose --profile tools run --rm backup
find backups -type f -name 'salon-*.dump' -mtime +14 -delete
