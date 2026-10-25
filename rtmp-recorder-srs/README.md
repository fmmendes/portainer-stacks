# RTMP Recorder - SRS

Alternativa ao [Nginx](../rtmp-recorder-nginx/README.md) usando **SRS 5**
(`ossrs/srs:5`), cuja imagem publica possui ARM64 para Raspberry Pi 5 com SO
de 64 bits. Recebe RTMP diretamente de uma camera de vigilancia, grava uma
copia DVR nativa em FLV e produz trechos com sobreposicao pelo mesmo gravador
compartilhado da stack Nginx. Nao requer programas adicionais na camera.

## Deploy no Portainer

1. Use Docker Standalone com Compose e adicione a stack a partir de
   `rtmp-recorder-srs/docker-compose.yml`.
2. Mantenha disponiveis `srs.conf` e a pasta irma `rtmp-recorder-common/`.
3. Configure os valores na secao **Environment variables** do Portainer.
   Nao ha credenciais embutidas nem necessidade de um `.env` versionado.
4. Disponibilize os bind mounts no host do Docker e aguarde os auxiliares
   saudaveis antes de habilitar o RTMP da camera.

| Variavel | Default | Funcao |
|---|---|---|
| `RTMP_APP_NAME` | `live` | Aplicacao permitida para publicacao |
| `RTMP_STREAM_NAME` | `stream` | Nome/chave do stream permitido |
| `RTMP_RECORD_ENABLED` | `on` | Habilita/desabilita DVR e arquivos com sobreposicao |
| `RTMP_RECORD_PATH` | `/recordings` | Diretorio interno; aceita subdiretorios de `/recordings` |
| `RTMP_RECORD_UNIQUE` | `on` | Pasta unica por sessao no gravador compartilhado |
| `RTMP_SEGMENT_MINUTES` | `2` | Intervalo inteiro, em minutos |
| `RTMP_OVERLAP_SECONDS` | `1` | Borda minima por lado, em segundos |
| `RTMP_PORT` / `HTTP_PORT` | `1935` / `8080` | Portas publicadas no host |
| `RTMP_BIND_ADDRESS` / `HTTP_BIND_ADDRESS` | `0.0.0.0` | Interfaces do host |
| `RECORDINGS_PATH` | `./recordings` | Diretorio persistente no host |
| `SRS_CONFIG_FILE` | `./srs.conf` | Template SRS no host |
| `RECORDER_SUPPORT_PATH` | `../rtmp-recorder-common` | Scripts compartilhados |
| `SRS_IMAGE` | `ossrs/srs:5` | Imagem SRS com ARM64 |

Os defaults sao usados quando as variaveis estao ausentes ou vazias.
Veja [todos os parametros e limites](../rtmp-recorder-common/README.md).
`RTMP_RECORD_UNIQUE=off` remove somente a pasta por sessao do auxiliar;
o DVR do SRS sempre mantem timestamps nos nomes dos segmentos para nao
sobrescreve-los na rotacao.

### Caminhos e permissoes

O Compose monta `./recordings` em `/recordings`, o template em
`/usr/local/srs/conf/recorder.conf` (somente leitura) e a configuracao expandida
em `/runtime/server.conf`. O SRS usa esta ultima configuracao.

Se sua edicao do Portainer nao resolver bind mounts relativos de stacks Git,
clone o repositorio no host do Docker e informe caminhos absolutos:

```text
SRS_CONFIG_FILE=/srv/portainer-stacks/rtmp-recorder-srs/srs.conf
RECORDER_SUPPORT_PATH=/srv/portainer-stacks/rtmp-recorder-common
RECORDINGS_PATH=/srv/rtmp-recorder-srs/recordings
PUID=1000
PGID=1000
```

Prepare o diretorio dedicado:

```sh
sudo mkdir -p /srv/rtmp-recorder-srs/recordings
sudo chown 1000:1000 /srv/rtmp-recorder-srs/recordings
```

A inicializacao ajusta somente os diretorios da gravacao para `PUID:PGID`
e abandona root. SRS e FFmpeg ja rodam com esses IDs.

Para rodar Nginx e SRS simultaneamente no mesmo Raspberry Pi, use diretorios
distintos e, por exemplo, `RTMP_PORT=1936` e `HTTP_PORT=8081` **nesta stack**.
As portas internas dos containers permanecem inalteradas.

## Envio direto pela camera

Configure video **H.264** e audio **AAC** ou sem audio. H.265 e G.711 nao
sao suportados sem conversao. Configure keyframes a cada 1 ou 2 segundos,
sempre dentro de `RTMP_MAX_GOP_SECONDS` (10 por padrao).

URL completa com os defaults:

```text
rtmp://<host>:1935/live/stream
```

Formato parametrizado: `rtmp://<host>:${RTMP_PORT}/${RTMP_APP_NAME}/${RTMP_STREAM_NAME}`.
Substitua tudo pelos valores reais no painel da camera.

Se houver campos separados, informe servidor `rtmp://<host>:1935`,
aplicacao `live` e chave/nome `stream`. Alguns fabricantes pedem
`rtmp://<host>:1935/live` no campo servidor. Use o IP/DNS do Raspberry Pi
acessivel pela camera, nao `localhost`.

Cada stack recebe uma camera com o nome configurado; outras aplicacoes e nomes
sao rejeitados pelo callback de publicacao. Para mais cameras, crie deploys
separados, com outras portas e diretorios.

## Gravacoes, status e cuidados

Os FLVs com sobreposicao ficam em
`./recordings/overlap/<stream>/<sessao>/`. A copia DVR nativa, sem sobreposicao,
fica em `./recordings/native/<app>/`, com segmentos ajustados a keyframes.
`RTMP_RECORD_PATH=/recordings/camera` acrescenta `camera/` a esses caminhos.

Reserve aproximadamente duas vezes o espaco do stream, mais as bordas
duplicadas. Nao existe limpeza automatica: para operacao 24/7, monitore espaco
e estabeleca retencao externa. Consulte as
[garantias de rotacao e limitacoes](../rtmp-recorder-common/README.md#rotacao-e-integridade).

Acesse `http://<host>:8080/api/v1/versions` ou
`http://<host>:8080/api/v1/summaries` para status JSON, e
`http://<host>:8080/api/v1/streams` para os streams ativos.
Nao e uma pagina HTML e nao serve os videos gravados.

RTMP e API HTTP nao tem autenticacao nem TLS. Restrinja ambos com firewall,
rede confiavel ou VPN; nao exponha a API administrativa publicamente.
O nome/chave do stream nao e um mecanismo de autenticacao.

Referencia: [SRS 5 - Getting Started](https://ossrs.io/lts/en-us/docs/v5/doc/getting-started).
