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

## Erro interno de token (Signature verification failed)

Se aparecer erro interno como `Invalid auth token: Signature verification failed`, o problema normalmente e divergencia de segredo interno entre componentes (`api-server`, `scheduler`, `dag-processor`) ou segredo vazio.

No compose atual, as variaveis abaixo sao obrigatorias e devem ter o mesmo valor para todos os servicos:

```bash
AIRFLOW__CORE__FERNET_KEY=<fernet_key_fixa>
AIRFLOW__API_AUTH__JWT_SECRET=<jwt_secret_fixo>
AIRFLOW__API_AUTH__JWT_ISSUER=airflow
```

### Gerar segredos (uma vez)

Opcao 1: PowerShell

```powershell
# Gera 32 bytes aleatorios para Fernet (base64url)
$fernetBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($fernetBytes)
$fernet = [Convert]::ToBase64String($fernetBytes).Replace('+','-').Replace('/','_')

# Gera segredo JWT forte (64 bytes, base64url sem padding)
$jwtBytes = New-Object byte[] 64
[System.Security.Cryptography.RandomNumberGenerator]::Fill($jwtBytes)
$jwtSecret = [Convert]::ToBase64String($jwtBytes).Replace('+','-').Replace('/','_').TrimEnd('=')

Write-Host "AIRFLOW__CORE__FERNET_KEY=$fernet"
Write-Host "AIRFLOW__API_AUTH__JWT_SECRET=$jwtSecret"
Write-Host "AIRFLOW__API_AUTH__JWT_ISSUER=airflow"
```

Opcao 2: shell (Linux/macOS) com Python

```bash
python3 - <<'PY'
from cryptography.fernet import Fernet
import secrets
print('AIRFLOW__CORE__FERNET_KEY=' + Fernet.generate_key().decode())
print('AIRFLOW__API_AUTH__JWT_SECRET=' + secrets.token_urlsafe(64))
print('AIRFLOW__API_AUTH__JWT_ISSUER=airflow')
PY
```

Guarde esses valores nas variaveis de ambiente da stack no Portainer (ou no seu gerenciador de segredos) e nao troque sem planejamento.

### Aplicar e validar

```bash
docker compose -f airflow/docker-compose.yml up -d --force-recreate airflow-init api-server dag-processor scheduler
docker compose -f airflow/docker-compose.yml ps
docker compose -f airflow/docker-compose.yml logs -f scheduler dag-processor api-server
```

Esperado: tasks saem de `queued` para `running` sem erro de assinatura de token.

### Recomendação adicional

Evite usar `apache/airflow:latest-python3.14` em produção. Prefira fixar uma versão explícita da imagem para reduzir quebras inesperadas em upgrades.
