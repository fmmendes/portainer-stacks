# Icinga stack notes

This folder contains the Icinga stacks (Master, Web, IcingaDB).

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

### Web stack (Nginx)

Required:

- `ICINGA_WEB_SERVER_NAME`
- `ICINGA_WEB_CERT_DOMAIN`
- `ICINGA_WEB_LE_LIVE_DIR` (example: `/etc/letsencrypt/live/<domain>`)
- `ICINGA_WEB_LE_ARCHIVE_DIR` (example: `/etc/letsencrypt/archive/<domain>`)

Optional:

- `ICINGA_WEB_CLIENT_MAX_BODY_SIZE` (default: `64m`)

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

## Master (API + IcingaDB integration)

- The Icinga 2 API is exposed on port `5665`.
- For IcingaDB, enable the Icinga 2 feature `icingadb` and point it to the Redis service from the IcingaDB stack.
