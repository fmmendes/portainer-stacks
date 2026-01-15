# Icinga stack notes

This folder contains the Icinga stacks (Master, Web, IcingaDB).

## Persistent data paths (/srv)

These stacks use bind-mounts for persistent data. By default, all persistent paths live under `/srv/`.

### Permissions

When using bind-mounts, the container process must be able to write to the host directory.

The `icinga/icinga2` container runs as the `icinga` user (UID `5665`). If you see errors like `mkdir /data/etc: permission denied`, fix ownership/permissions for the master data directory:

```bash
mkdir -p /srv/icinga/master/data
chown -R 5665:5665 /srv/icinga/master/data
chmod -R u+rwX,g+rwX /srv/icinga/master/data
```

For `icinga/icingaweb2`, the container also initializes its configuration under `/data`. If you see errors like `mkdir /data/etc/icingaweb2/...: permission denied`, fix the permissions for the Web data directory.

Because the UID can vary by image version, check it first on the Docker host:

```bash
docker run --rm icinga/icingaweb2:2 id -u
docker run --rm icinga/icingaweb2:2 id -g
```

Then apply ownership (replace `<UID>` and `<GID>` with the values printed above):

```bash
mkdir -p /srv/icinga/web/data
chown -R <UID>:<GID> /srv/icinga/web/data
chmod -R u+rwX,g+rwX /srv/icinga/web/data
```

Create the directories on the machine that runs Docker:

```bash
mkdir -p \
	/srv/icinga/master/data \
	/srv/icinga/web/nginx-log \
	/srv/icinga/web/data \
	/srv/icinga/icingadb/redis-data \
	/srv/icinga/icingadb/data
```

Or run the helper script:

```bash
sh ./mkdir-srv-paths.sh
```

## Shared network (required)

The Master and IcingaDB stacks must share an external Docker network so Icinga 2 can write to the IcingaDB Redis instance (Icinga 2 feature `icingadb`).

Create it once:

```bash
docker network create icinga-shared
```

## External PostgreSQL

No compose file in this folder runs PostgreSQL.

Your external PostgreSQL must provide:

- A database/user for **Icinga Web 2**
- A database/user for **IcingaDB**

Credentials are passed via environment variables.

## Icinga Web 2 (HTTPS on 8443)

The Web stack exposes HTTPS on port `8443` and reuses existing Let’s Encrypt certificates via bind-mounts.

Expected files (Let’s Encrypt):

- `fullchain.pem`
- `privkey.pem`

## Environment variables reference

Set these values in Portainer (or an `.env` file) before deploying.

### Common

- `TZ` (optional, default: `America/Sao_Paulo`)

### Master stack (bind-mount paths)

Optional (with defaults):

- `ICINGA_MASTER_DATA_DIR` (default: `/srv/icinga/master/data`)

### Web stack (Nginx)

Required:

- `ICINGA_WEB_SERVER_NAME`
- `ICINGA_WEB_CERT_DOMAIN`
- `ICINGA_WEB_LE_LIVE_DIR` (example: `/etc/letsencrypt/live/<domain>`)
- `ICINGA_WEB_LE_ARCHIVE_DIR` (example: `/etc/letsencrypt/archive/<domain>`)

Optional:

- `ICINGA_WEB_CLIENT_MAX_BODY_SIZE` (default: `64m`)
- `ICINGA_WEB_NGINX_LOG_DIR` (default: `/srv/icinga/web/nginx-log`)

### Web stack (Icinga Web 2)

Required:

- `ICINGAWEB2_BASE_URL`
- `ICINGAWEB2_DB_HOST`
- `ICINGAWEB2_DB_PASSWORD`
- `ICINGA2_API_HOST`

Optional (with defaults):

- `ICINGAWEB2_DB_TYPE` (default: `pgsql`)
- `ICINGAWEB2_DB_PORT` (default: `5432`)
- `ICINGAWEB2_DB_NAME` (default: `icingaweb2`)
- `ICINGAWEB2_DB_USER` (default: `icingaweb2`)
- `ICINGA2_API_PORT` (default: `5665`)
- `ICINGA2_API_USER` (default: `icingaweb2`)
- `ICINGA2_API_PASSWORD` (default: `CHANGE_ME`)
- `PHP_MEMORY_LIMIT` (default: `256M`)
- `PHP_MAX_EXECUTION_TIME` (default: `60`)
- `PHP_POST_MAX_SIZE` (default: `64M`)
- `PHP_UPLOAD_MAX_FILESIZE` (default: `64M`)

Bind-mount paths (optional, with defaults):

- `ICINGA_WEB2_DATA_DIR` (default: `/srv/icinga/web/data`)

### IcingaDB stack

Required:

- `ICINGADB_DATABASE_HOST`
- `ICINGADB_DATABASE_PASSWORD`

Optional (with defaults):

- `ICINGADB_REDIS_HOST` (default: `redis-icingadb`)
- `ICINGADB_REDIS_PORT` (default: `6379`)
- `ICINGADB_DATABASE_TYPE` (default: `pgsql`)
- `ICINGADB_DATABASE_PORT` (default: `5432`)
- `ICINGADB_DATABASE_DATABASE` (default: `icingadb`)
- `ICINGADB_DATABASE_USER` (default: `icingadb`)
- `ICINGADB_LOGGING_LEVEL` (default: `info`)
- `ICINGADB_LOGGING_OUTPUT` (default: `console`)

Bind-mount paths (optional, with defaults):

- `ICINGADB_REDIS_DATA_DIR` (default: `/srv/icinga/icingadb/redis-data`)
- `ICINGADB_DATA_DIR` (default: `/srv/icinga/icingadb/data`)

## Master (API + IcingaDB integration)

- The Icinga 2 API is exposed on port `5665`.
- For IcingaDB, enable the Icinga 2 feature `icingadb` and point it to the Redis service from the IcingaDB stack.
