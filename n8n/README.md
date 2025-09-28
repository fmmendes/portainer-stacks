# Before deploy

```bash
sudo mkdir -p /srv/n8n/data
sudo mkdir -p /srv/n8n/files
sudo mkdir -p /srv/n8n/nginx/templates

sudo chown -R 1000:1000 /srv/n8n
```

## Certificados (Certbot no host)

Este repositório assume que o Certbot roda no host e que você já possui um A record apontando para o IP do host.

 O serviço do `docker-compose` espera que os certificados legíveis para containers sejam colocados em `/srv/n8n/certs` no host e montados no container como:

 - `/srv/n8n/certs/fullchain.pem` -> montado como `/certs/fullchain.pem` no container
 - `/srv/n8n/certs/privkey.pem`  -> montado como `/certs/privkey.pem` no container

 Com isso, o processo dentro do container (n8n) consegue ler os arquivos sem precisar de acesso direto a todo `/etc/letsencrypt` (que geralmente contém arquivos com permissões restritas e symlinks para `/etc/letsencrypt/archive`).

### Obter certificado via Route53

Se não for o profile default use

```bash
export AWS_PROFILE=${ProfileName}
```

```bash
certbot certonly \
	--dns-route53 \
	--dns-route53-propagation-seconds 30 \
	-d ${SUBDOMAIN}.${DOMAIN_NAME} \
	-m my-email@outlook.com
```

### Hook de renovação: copiar certificados e reiniciar o container n8n
- copie os arquivos reais dos certificados (seguindo symlinks) para um diretório legível por containers (/srv/n8n/certs);
- ajuste permissões para que o processo dentro do container n8n consiga ler a chave privada;
- reinicie o container `n8n` para que o processo Node carregue o novo certificado.

No host, crie o arquivo `/etc/letsencrypt/renewal-hooks/deploy/reload-n8n.sh` com o conteúdo abaixo:

```bash
#!/bin/bash
set -euo pipefail

DEST_DIR="/srv/n8n/certs"

if [ -z "${CERTBOT_DOMAIN:-}" ]; then
	echo "CERTBOT_DOMAIN not set - nothing to do"
	exit 0
fi

SUB="${CERTBOT_DOMAIN}"

mkdir -p "$DEST_DIR"

# copia seguindo symlinks e garante permissões legíveis pelo container
cp -L "/etc/letsencrypt/live/${SUB}/fullchain.pem" "$DEST_DIR/fullchain.pem"
cp -L "/etc/letsencrypt/live/${SUB}/privkey.pem"  "$DEST_DIR/privkey.pem"
chown root:root "$DEST_DIR"/*.pem || true
chmod 644 "$DEST_DIR"/*.pem || true

# tenta reiniciar o container n8n para aplicar os novos certificados
if command -v docker >/dev/null 2>&1; then
	if docker ps --format '{{.Names}}' | grep -q '^n8n$'; then
		echo "Reiniciando container 'n8n'..."
		docker restart n8n || {
			echo "Falha ao reiniciar 'n8n' com docker restart - registrando e saindo com sucesso para não atrapalhar renew"
		}
	else
		echo "Container 'n8n' não encontrado; skipping restart."
	fi
else
	echo "docker não disponível no host; skipping restart"
fi

exit 0
```

Torne executável o hook criado:

```bash
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-n8n.sh
```

O Certbot executará esse script automaticamente após cada renovação bem-sucedida (deploy hook).
