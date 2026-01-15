#!/usr/bin/env sh
set -eu

# Creates default bind-mount directories used by the Icinga stacks.
# Run this on the machine that hosts the Docker engine.

mkdir -p \
  /srv/icinga/master/etc \
  /srv/icinga/master/var \
  /srv/icinga/master/log \
  /srv/icinga/web/nginx-log \
  /srv/icinga/web/etc-icingaweb2 \
  /srv/icinga/web/var-icingaweb2 \
  /srv/icinga/icingadb/redis-data \
  /srv/icinga/icingadb/data

echo "Created /srv bind-mount directories for Icinga stacks."
