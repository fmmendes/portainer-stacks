#!/usr/bin/env sh
set -eu

# Creates default bind-mount directories used by the Icinga stacks.
# Run this on the machine that hosts the Docker engine.

mkdir -p \
  /srv/icinga/master/data \
  /srv/icinga/web/nginx-log \
  /srv/icinga/web/data \
  /srv/icinga/icingadb/redis-data \
  /srv/icinga/icingadb/data

# If you run into permissions issues, ensure the container user can write to these paths.
# The icinga/icinga2 image runs as UID 5665.
# Uncomment if needed:
# chown -R 5665:5665 /srv/icinga/master/data

echo "Created /srv bind-mount directories for Icinga stacks."
