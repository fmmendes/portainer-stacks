# Before deploy

```bash
sudo mkdir -p /srv/n8n/data
sudo mkdir -p /srv/n8n/files
sudo mkdir -p /srv/n8n/nginx/templates

sudo chown -R 1000:1000 /srv/n8n
```

## Certificados (Certbot no host)

Este repositório assume que o Certbot roda no host e que você já possui um A record apontando para o IP do host.

O `nginx` do `docker-compose` monta os arquivos de certificado do host como:

 - `/etc/letsencrypt/live/${SUBDOMAIN}.${DOMAIN_NAME}/fullchain.pem` -> montado como `/certs/${SUBDOMAIN}.${DOMAIN_NAME}.crt` no container
 - `/etc/letsencrypt/live/${SUBDOMAIN}.${DOMAIN_NAME}/privkey.pem` -> montado como `/certs/${SUBDOMAIN}.${DOMAIN_NAME}.key` no container

Com isso, o nginx usa esses dois arquivos e não precisa de acesso a todo `/etc/letsencrypt`.

### Obter certificado via Route53 (como você usa)

Se o seu Certbot já está configurado com o plugin Route53 (já funcionando), o comando que você informou é exatamente o que deve ser usado. Exemplo (use os seus valores):

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

### Reload do nginx após renovação

Como você já usa o `certbot.timer` no host para renovação automática, o approach recomendado é adicionar um *renewal-hook* que recarregue o nginx dentro do container `n8n-nginx` criado pelo Compose/Portainer.

No host crie o arquivo `/etc/letsencrypt/renewal-hooks/post/reload-n8n-nginx.sh` com o conteúdo abaixo:

```bash
#!/bin/sh
# Recarrega nginx no container chamado n8n-nginx (Portainer/Compose)
docker exec n8n-nginx nginx -s reload || true

```

Torne executável:

```bash
sudo chmod +x /etc/letsencrypt/renewal-hooks/post/reload-n8n-nginx.sh
```

Esse script será executado automaticamente pelo Certbot após cada renovação bem-sucedida.

### Comandos úteis
Verificar que os arquivos de certificado foram montados corretamente dentro do container:

```bash
docker compose exec n8n-nginx ls -l /certs
```

E recarregar nginx manualmente (quando necessário):

```bash
docker compose exec n8n-nginx nginx -s reload
```
