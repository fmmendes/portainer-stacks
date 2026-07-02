```sql
CREATE DATABASE airflow_db;
CREATE USER airflow_user WITH PASSWORD 'airflow_pass';
GRANT ALL PRIVILEGES ON DATABASE airflow_db TO airflow_user;

-- PostgreSQL 15 requires additional privileges:
-- Note: Connect to the airflow_db database before running the following GRANT statement
-- You can do this in psql with: \c airflow_db
GRANT ALL ON SCHEMA public TO airflow_user;
```

## Troubleshooting: erro no dag-processor ao adicionar a primeira DAG

### Sintomas

Nos logs do serviço `dag-processor`, podem aparecer mensagens como:

- `Permission denied: '/opt/airflow/logs/dag_processor'`
- `FileNotFoundError` para arquivos em `/opt/airflow/logs/dag_processor/...`

### Causa raiz

O volume de logs mapeado no host (`/srv/airflow/logs`) não está com permissões adequadas para escrita pelo usuário do Airflow dentro do container.

### Como corrigir

No host Linux onde o Docker está rodando:

```bash
sudo mkdir -p /srv/airflow/dags /srv/airflow/logs /srv/airflow/plugins /srv/airflow/config
sudo chown -R 1000:1000 /srv/airflow
sudo chmod -R g+rwX /srv/airflow
```

Observacao: este stack esta configurado para executar os containers com usuario `1000:0`.

Depois, recrie os serviços do stack:

```bash
docker compose -f airflow/docker-compose.yml up -d --force-recreate airflow-init dag-processor scheduler api-server
```

### Como validar

```bash
docker compose -f airflow/docker-compose.yml logs -f dag-processor
```

Se as permissões estiverem corretas, o `dag-processor` volta a processar os arquivos sem os erros acima.

## Airflow Configuration na UI (403 Forbidden)

Se a pagina "Airflow Configuration" retornar 403, habilite a exposicao da configuracao no webserver:

```yaml
AIRFLOW__WEBSERVER__EXPOSE_CONFIG: 'true'
```

No compose atual este parametro ja esta definido. Depois de alterar, recrie os servicos para aplicar.

### Recomendação adicional

Evite usar `apache/airflow:latest-python3.14` em produção. Prefira fixar uma versão explícita da imagem para reduzir quebras inesperadas em upgrades.
