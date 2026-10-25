# Gravador compartilhado RTMP/FLV

Suporte utilizado pelas stacks [Nginx](../rtmp-recorder-nginx/README.md) e
[SRS](../rtmp-recorder-srs/README.md). Nao e uma stack independente.
Nao precisa instalar dependencias no Raspberry Pi nem construir imagens.

O fluxo e: **camera RTMP -> Nginx/SRS -> FFmpeg continuo -> gravador Python**.
O servidor tambem salva uma copia nativa separada. Cada deploy aceita um stream
H.264 com audio AAC opcional. O FFmpeg usa `-c copy`: nao recodifica nem abre
uma nova conexao para cada segmento. Somente RTMP e status sao publicados no
host; as portas auxiliares 1936, 9000 e 9001 ficam na rede interna do Compose.

## Rotacao e integridade

O auxiliar le uma unica sequencia FLV e copia os payloads de todos os pacotes
de audio e video para os arquivos, sem descartar tags na troca de trechos.
Durante as bordas, escreve os mesmos pacotes nos dois arquivos. Reutiliza o
keyframe anterior ao inicio desejado para que o novo FLV possa ser decodificado
independentemente. A sobreposicao pode, portanto, ser maior que a configurada;
nao se promete duracao exata de 122 segundos para cameras com GOP arbitrario.

Com `RTMP_SEGMENT_MINUTES=2`, `RTMP_OVERLAP_SECONDS=1`,
`RTMP_ALIGN_CLOCK=on` e `RTMP_CLOCK_OFFSET_MINUTES=1`, os alvos sao:

```text
trecho 1: 00:54:59 -- 00:57:01  (nucleo: minutos 55 e 56)
trecho 2: 00:56:59 -- 00:59:01  (nucleo: minutos 57 e 58)
```

O inicio pode ser antecipado ate um keyframe; o fim inclui o primeiro pacote
que atinge a borda final. O primeiro e o ultimo arquivo da sessao podem ser
parciais: nao existe video anterior a conexao nem posterior a desconexao.
O alinhamento usa UTC do host, ancorado no inicio de cada conexao, e os timestamps
do stream para avancar. Mantenha o relogio do host sincronizado. Um stream muito
atrasado ou com timestamps incorretos nao permite garantir alinhamento exato
com o horario real da cena.

O encaminhamento pode comecar somente no primeiro keyframe apos o handshake
(especialmente no Nginx), e buffers do encaminhador podem nao ser drenados
inteiramente quando a camera desconecta (especialmente no SRS). Assim, os
arquivos com sobreposicao nao substituem a copia nativa para preservar as
bordas da conexao. Isso e distinto da rotacao: durante uma conexao continua,
o auxiliar nao reinicia a captura nem descarta pacotes para trocar arquivos.

**A propriedade de nao perder frames aplica-se a rotacao dos pacotes completos
recebidos pelo gravador**, nao a toda falha possivel de captura. Nem RTMP/TCP
permite garantir frames que a camera nao enviou, indisponibilidade dos
containers, atraso/falha de encaminhamento, desconexao, disco cheio, queda de
energia ou timestamps/codecs invalidos. A copia nativa permanece independente
do auxiliar para facilitar recuperacao quando o encaminhamento falhar.
Mudancas de codec/configuracao da camera devem iniciar uma nova conexao.

O buffer de sobreposicao e limitado por memoria e intervalo maximo de keyframes.
Ultrapassar os limites, receber FLV truncado/corrompido ou falhar ao escrever
gera erro explicito nos logs e encerra o auxiliar; o Compose o reinicia.
O FFmpeg tambem e reiniciado apos desconexao para aceitar a reconexao do
encaminhador. Isso nao e failover sem interrupcao: consulte a copia nativa
quando houver falhas.

Arquivos em andamento usam `.flv.part`. Apos fechamento e `fsync`, tornam-se
`.flv` por renomeacao atomica. Na parada normal, os trechos finais sao fechados.
Apos interrupcao abrupta, `.part` sao preservados para recuperacao manual, nao
apagados ou apresentados como arquivos concluidos. O ultimo pacote pode estar
incompleto. A copia nativa usa os mecanismos de fechamento do Nginx/SRS.

Nao ha retencao automatica. O volume cresce continuamente; planeje o disco
para a copia nativa, os trechos com sobreposicao e a margem de operacao.
Nao remova `.part` ativos nem arquivos nativos abertos por politica de limpeza.

## Variaveis compartilhadas

Defina estes valores em **Environment variables** no Portainer de cada stack.

| Variavel | Default | Restricoes e comportamento |
|---|---|---|
| `RTMP_APP_NAME` | `live` | Letras ASCII, numeros, `_` e `-` |
| `RTMP_STREAM_NAME` | `stream` | Mesmo conjunto de caracteres; um stream por deploy |
| `RTMP_RECORD_ENABLED` | `on` | `on` ou `off`; controla arquivos nativos e com sobreposicao |
| `RTMP_RECORD_PATH` | `/recordings` | Caminho absoluto dentro de `/recordings`, sem `..` ou espacos |
| `RTMP_RECORD_UNIQUE` | `on` | `on`: diretorio de sessao com UUID; `off`: arquivos diretamente em `overlap/<stream>/` |
| `RTMP_SEGMENT_MINUTES` | `2` | Inteiro >= 1 |
| `RTMP_OVERLAP_SECONDS` | `1` | Inteiro >= 0; menor que metade do intervalo |
| `RTMP_ALIGN_CLOCK` | `on` | `off` conta os intervalos a partir do inicio da sessao |
| `RTMP_CLOCK_OFFSET_MINUTES` | `0` | Inteiro entre 0 e intervalo-1; `1` alinha intervalos de 2 minutos aos minutos impares |
| `RTMP_MAX_GOP_SECONDS` | `10` | Inteiro entre 1 e a duracao do intervalo; ajuste tambem o IDR na camera |
| `RTMP_MAX_BUFFER_MB` | `64` | Limite do buffer de pacotes em MiB, inteiro >= 1 |
| `PUID` / `PGID` | `1000` / `1000` | IDs nao-root donos dos diretorios dedicados |
| `PYTHON_IMAGE` | `python:3.13-alpine` | Imagem do auxiliar, com suporte ARM64 |
| `FFMPEG_IMAGE` | `linuxserver/ffmpeg:9.0.2` | Imagem FFmpeg multiarch com suporte ARM64 |
| `FFMPEG_LOG_LEVEL` | `warning` | Nivel de logs do FFmpeg |

`RTMP_RECORD_UNIQUE=off` deixa de isolar sessoes: reconexoes com o mesmo nome
e inicio no mesmo segundo podem substituir arquivos anteriores com o mesmo
nome, e `.part` existentes causam erro em vez de sobrescrita silenciosa.
Para preservar todas as sessoes, mantenha `on`.
O DVR do SRS sempre usa timestamps por segmento; o Nginx mantem o timestamp
no sufixo mesmo com `record_unique off`.

Variaveis invalidas impedem a inicializacao com erro. O template aceita somente
placeholders explicitamente permitidos; variaveis internas do Nginx nao sao
substituidas. Ao atualizar valores no Portainer, recrie todos os servicos da
stack para aplicar a mesma configuracao ao servidor e aos auxiliares.

Os overrides de imagem devem preservar executaveis, caminhos e compatibilidade
ARM64. A verificacao dos manifestos nao substitui um teste no Raspberry Pi real.

## Testes locais do algoritmo

Com Python 3.13:

```sh
python3 -m unittest discover -s rtmp-recorder-common -p 'test_*.py' -v
```

Os testes verificam preservacao dos payloads de audio/video entre rotacoes,
sobreposicao mensuravel, keyframes, alinhamento, limites, callbacks dos dois
servidores e rollover dos timestamps FLV em streams longos.
