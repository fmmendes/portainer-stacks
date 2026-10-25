# RTMP Recorder - Nginx

Recebe o RTMP nativo de uma camera de vigilancia e grava FLVs continuamente.
Nao e necessario executar programas na camera: basta configurar o destino RTMP.
Os trechos principais tem intervalo padrao de **2 minutos**, com bordas de pelo
menos **1 segundo** para cada lado e sem recodificacao.

A imagem utilizada e `tiangolo/nginx-rtmp`, com manifestos AMD64 e ARM64
verificados. A substituicao de `alfg/nginx-rtmp` foi autorizada porque os tags
publicos desta ultima disponibilizavam somente AMD64. Use um sistema operacional
ARM64 no Raspberry Pi 5; nao e necessaria emulacao.

## Deploy no Portainer

Use Docker Standalone com suporte a Compose e `depends_on` com condicoes de saude.
Mantenha tambem a pasta irma `rtmp-recorder-common/`: ela contem o gravador
compartilhado com a [alternativa SRS](../rtmp-recorder-srs/README.md).

1. Adicione uma stack usando `rtmp-recorder-nginx/docker-compose.yml`.
2. Em **Environment variables**, informe os valores desejados; os defaults do
   Compose sao usados para variaveis ausentes ou vazias. Nao ha credenciais
   embutidas nem necessidade de commitar um arquivo `.env`.
3. Disponibilize os bind mounts no **host do Docker**, nao apenas no navegador
   do Portainer. Veja os caminhos e permissoes abaixo.
4. Faca o deploy e espere `nginx-recorder` e `nginx-ffmpeg` ficarem saudaveis antes de habilitar
   o envio da camera.

| Variavel | Default | Funcao |
|---|---|---|
| `RTMP_APP_NAME` | `live` | Aplicacao RTMP |
| `RTMP_STREAM_NAME` | `stream` | Nome do stream/chave de publicacao da camera |
| `RTMP_RECORD_ENABLED` | `on` | `on` grava; `off` desabilita os dois tipos de arquivo |
| `RTMP_RECORD_PATH` | `/recordings` | Diretorio no container; aceita subdiretorios de `/recordings` |
| `RTMP_RECORD_UNIQUE` | `on` | Pasta unica por sessao no gravador auxiliar e `record_unique` do Nginx |
| `RTMP_SEGMENT_MINUTES` | `2` | Intervalo inteiro, em minutos |
| `RTMP_OVERLAP_SECONDS` | `1` | Borda minima por lado, em segundos |
| `RTMP_PORT` / `HTTP_PORT` | `1935` / `8080` | Portas publicadas no host |
| `RTMP_BIND_ADDRESS` / `HTTP_BIND_ADDRESS` | `0.0.0.0` | Interfaces do host |
| `RECORDINGS_PATH` | `./recordings` | Diretorio persistente no host |
| `NGINX_CONFIG_FILE` | `./nginx.conf` | Template no host |
| `RECORDER_SUPPORT_PATH` | `../rtmp-recorder-common` | Scripts compartilhados no host |
| `NGINX_IMAGE` | `tiangolo/nginx-rtmp:latest-2026-10-19` | Imagem Nginx multiarch |

Os demais parametros, limites, imagens auxiliares e o comportamento preciso da
rotacao estao no [guia do gravador](../rtmp-recorder-common/README.md).

### Arquivos, permissoes e caminhos relativos

Por padrao, `./nginx.conf` e montado em `/etc/nginx/nginx.conf` (somente leitura)
e `./recordings` em `/recordings`. O auxiliar expande exclusivamente os
placeholders permitidos e gera `/runtime/server.conf`; o Nginx utiliza esse
arquivo porque **Nginx nao expande variaveis de ambiente diretamente**.
`RTMP_RECORD_ENABLED=on` e convertido para `record all`, pois `record on`
nao e uma diretiva valida do modulo.

Para deploy por Git, habilite a resolucao de caminhos relativos do Portainer,
caso sua edicao ofereca esse recurso. Sem esse suporte, clone o repositorio no
host do Docker e defina caminhos absolutos, por exemplo:

```text
NGINX_CONFIG_FILE=/srv/portainer-stacks/rtmp-recorder-nginx/nginx.conf
RECORDER_SUPPORT_PATH=/srv/portainer-stacks/rtmp-recorder-common
RECORDINGS_PATH=/srv/rtmp-recorder-nginx/recordings
PUID=1000
PGID=1000
```

Antes do deploy, crie somente o diretorio destinado a esta stack:

```sh
sudo mkdir -p /srv/rtmp-recorder-nginx/recordings
sudo chown 1000:1000 /srv/rtmp-recorder-nginx/recordings
```

A inicializacao ajusta o dono dos diretorios de gravacao para `PUID:PGID`, sem
alterar recursivamente arquivos existentes, e abandona privilegios de root.
Nginx e FFmpeg rodam diretamente com esses IDs. O volume `runtime` contem somente
a configuracao gerada, nao os videos.

## Configuracao da camera

Selecione **H.264** para video e **AAC** para audio, ou desative o audio.
H.265, G.711 e outros codecs exigem conversao e nao sao suportados nesta stack.
Configure um keyframe/IDR a cada 1 ou 2 segundos; nao ultrapasse
`RTMP_MAX_GOP_SECONDS` (padrao: 10).

Se a camera possuir um campo de URL completa:

```text
rtmp://<host>:1935/${RTMP_APP_NAME}/stream
```

Com os defaults, use `rtmp://<host>:1935/live/stream`. Substitua as variaveis
pelos valores reais: a camera nao interpreta `${...}`. Se alterar
`RTMP_STREAM_NAME`, substitua tambem o ultimo componente.

Se os campos forem separados, use servidor `rtmp://<host>:1935`, aplicacao
`live` e nome/chave de stream `stream`; alguns fabricantes juntam servidor e
aplicacao como `rtmp://<host>:1935/live`. `<host>` e o IP ou DNS do Raspberry Pi
acessivel pela camera, nao `localhost`. Ajuste a porta se mudar `RTMP_PORT`.

Cada deploy aceita **uma camera/um nome de stream configurado**. Para mais
cameras, crie outras stacks com portas e diretorios distintos. Nomes divergentes
sao rejeitados explicitamente.

## Gravacoes e status

Os arquivos com sobreposicao ficam em
`./recordings/overlap/<stream>/<sessao>/` no host. O Nginx tambem grava uma
**copia nativa de seguranca**, sem sobreposicao, diretamente em `./recordings/`.
Essa copia usa o mesmo intervalo, com cortes em keyframes. O timestamp no sufixo
evita sobrescrita entre rotacoes mesmo com `record_unique off`.
Um `RTMP_RECORD_PATH=/recordings/camera` acrescenta `camera/` aos caminhos.

O armazenamento total e aproximadamente o dobro do video recebido, mais as
bordas duplicadas. Nao ha exclusao automatica: dimensione o disco para 24/7 e
defina uma politica externa de retencao. Leia as
[garantias e limitacoes](../rtmp-recorder-common/README.md#rotacao-e-integridade).

Acesse `http://<host>:8080/` ou `/stat` para o status RTMP em XML.
As gravacoes nao sao disponibilizadas por HTTP. RTMP e status nao tem
autenticacao nem TLS: use uma rede confiavel, firewall ou VPN. O nome do stream
nao funciona como senha.
