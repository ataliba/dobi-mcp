# dobi-mcp

MCP mínimo para agentes **XiaoZhi** (ex.: robô Dobi). Expõe tools somente leitura
e conecta na nuvem XiaoZhi por WebSocket de **saída** — nenhuma porta aberta no seu lado.

```
Nuvem XiaoZhi (wss) <──> pipe.py (ponte) <──stdio──> server.py (FastMCP)
```

## Tools

| Tool | O que faz |
|---|---|
| `calcular` | Expressões matemáticas via `simpleeval` (sem `eval`, sem RCE) |
| `data_hora` | Data/hora em America/Sao_Paulo |
| `status_servidor` | CPU, memória, disco e uptime do host |
| `proximos_feriados` | Próximos feriados nacionais/estaduais ([feriadosapi.com](https://feriadosapi.com)) |
| `dia_util_bancario` | Se a data é dia útil bancário e o próximo dia útil |

Personalizadas: o que estiver em `custom_tools/` (local, fora do git; veja abaixo).

## Rodando

1. Pegue o endpoint: xiaozhi.me/console/agents → Configurar função → **MCP Endpoint** (canto inferior direito).
2. Execute:

```bash
pip install -r requirements.txt
export MCP_ENDPOINT='wss://api.xiaozhi.me/mcp/?token=...'   # aspas simples!
python pipe.py server.py
```

Feriados: crie conta free em feriadosapi.com, gere token no dashboard e exporte
`FERIADOS_API_KEY` (opcional `FERIADOS_UF=SP` como estado padrão).

Ou em container (non-root, uid 10001). Tools oficiais vêm na imagem; as personalizadas
entram por volume read-only em `/app/custom_tools`:

```bash
docker compose up -d --build          # usa docker-compose.yml de exemplo
# ou, sem compose:
docker build -t dobi-mcp .
docker run -d --name dobi-mcp --restart unless-stopped --env-file .env \
  -e ENABLED_TOOLS=calculo,tempo,sistema,feriados \
  -v "$PWD/custom_tools:/app/custom_tools:ro" dobi-mcp
```

Os arquivos de `custom_tools/` precisam ser legíveis pelo uid 10001 (`chmod o+r custom_tools/*.py`).
Mudou uma tool oficial? Rebuild da imagem. Mudou uma personalizada? Só reinicie o container.

Sucesso = log `conectado em wss://api.xiaozhi.me/mcp/?token=***`. Depois pergunte
ao robô "quanto é 2 elevado a 10?" ou "como está o servidor?".

## Segredos via Infisical (opcional)

`USE_INFISICAL` liga/desliga o [Infisical](https://infisical.com) como fonte dos segredos
(`MCP_ENDPOINT`, `FERIADOS_API_KEY`, `FERIADOS_UF`):

- **Desligado** (padrão: ausente ou `0`): segredos vêm do ambiente/`.env`, como acima.
- **Ligado** (`1`, `true`, `yes`, `on` ou `sim`): o `pipe.py` se reexecuta sob
  `infisical run` e os segredos do projeto entram no ambiente antes de tudo.

| Variável | Uso |
|---|---|
| `USE_INFISICAL` | Liga/desliga |
| `INFISICAL_ENV` | Ambiente (`dev`, `staging`, `prod`); ausente = padrão do CLI (`dev`!) |
| `INFISICAL_PROJECT_ID` | ID do projeto; obrigatória sem `.infisical.json` (ex.: container) |
| `INFISICAL_PATH` | Pasta de segredos no projeto (padrão `/`) |
| `INFISICAL_API_URL` | Instância própria; vira `--domain` no login e no run |
| `INFISICAL_UNIVERSAL_AUTH_CLIENT_ID` / `_SECRET` | Machine identity (container/CI) — recomendado |
| `INFISICAL_TOKEN` | Token fixo (legado); ignorado quando há client-id/secret |

Só as variáveis definidas viram flags (`--env`, `--projectId`, `--path`, `--domain`). No boot sai
`segredos via Infisical (env=..., sessão Universal Auth)` em stderr.

**Sessão Universal Auth** (mesmo modelo do velhodorio): com client-id/secret no ambiente, o
`pipe.py` roda `infisical login --method=universal-auth --silent --plain` a cada boot, pega o
token de acesso de curta duração e só então faz `infisical run` com ele. Nada de token fixo
vencendo no `.env`: reiniciou, sessão nova. Client-id/secret chegam ao CLI pelo ambiente (não
por argumento, então não aparecem no `ps`) e o secret é removido do ambiente antes de subir o
servidor e as tools. Login falhou → o container sai com o erro do CLI (secret mascarado) e o
`restart: unless-stopped` tenta de novo.

**Local** (CLI instalado, login de usuário):

```bash
infisical login
infisical init                              # uma vez; gera .infisical.json
USE_INFISICAL=1 INFISICAL_ENV=dev python pipe.py server.py
```

**Container** (machine identity): o CLI do Infisical já vem na imagem; só o uso é opcional
(`USE_INFISICAL`). Crie uma machine identity com
Universal Auth (só leitura, só no ambiente/pasta necessários) e no `.env` coloque só o necessário
para autenticar:

```bash
# .env
INFISICAL_UNIVERSAL_AUTH_CLIENT_ID=...
INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET=...
INFISICAL_PROJECT_ID=...
INFISICAL_API_URL=https://infisical.exemplo.com   # se instância própria
```

```bash
USE_INFISICAL=1 docker compose up -d --build
# ou, sem compose:
docker build -t dobi-mcp .
docker run -d --name dobi-mcp --restart unless-stopped --env-file .env \
  -e USE_INFISICAL=1 -e INFISICAL_ENV=prod \
  -e ENABLED_TOOLS=calculo,tempo,sistema,feriados \
  -v "$PWD/custom_tools:/app/custom_tools:ro" dobi-mcp
```

No compose, `INFISICAL_ENV` padrão é `prod`.

Erros comuns:

- ``USE_INFISICAL ativo, mas o CLI `infisical` não está no PATH`` → instale o CLI
  (na imagem ele já vem), ou desligue com `USE_INFISICAL=0`.
- `Please either run infisical init ... or pass in project id with --projectId flag` →
  rode `infisical init` ou defina `INFISICAL_PROJECT_ID`.
- `login Universal Auth falhou (código 1): ...` → client-id/secret errados, identity sem
  Universal Auth ou `INFISICAL_API_URL` apontando para a instância errada.
- Sobe mas faltam segredos → `INFISICAL_ENV` ausente cai em `dev`; a identity precisa de
  permissão no ambiente onde os segredos estão (geralmente `prod`).

## Ativando tools

Duas origens de tools:

| Origem | Pasta | Onde vive |
|---|---|---|
| Oficial | `tools/` | Dentro da imagem (versionada com o projeto) |
| Personalizada | `CUSTOM_TOOLS_DIR` (padrão `custom_tools/`; container: `/app/custom_tools`) | Volume montado por você |

- **Oficiais:** nenhuma sobe só por existir em `tools/`; a ativação é explícita (abaixo).
- **Personalizadas:** estar no diretório = estar ativa. Para desligar, tire o arquivo (ou
  renomeie para começar com `_`).

Oficiais ativas:

1. `ENABLED_TOOLS` (env, separado por vírgula), ex.: `ENABLED_TOOLS=calculo,tempo`;
2. se ausente ou vazia, `config.yaml` → chave `enabled_tools`.

Oficial fora da lista **não é importada**. Nome na lista sem arquivo → warning, sem crash.
Personalizada com nome de uma oficial → ignorada com warning, mesmo que a oficial esteja
desligada (personalizada nunca se passa por oficial). Pasta de personalizadas inexistente →
só as oficiais sobem.
Nomes precisam casar com `^[a-z][a-z0-9_]*$` (bloqueia `../algo`; helpers com `_` nunca carregam).

No boot sai uma linha de inventário em stderr:

```
tools ativas (3): calculo, tempo, custom/minha_tool | ignoradas: '../x' (nome inválido), feriados (não habilitada)
```

## Criando uma tool

Oficial em `tools/<nome>.py`, personalizada em `custom_tools/<nome>.py` (sem
`__init__.py`; o mesmo formato vale para as duas). O arquivo exporta `register(mcp) -> None` e registre as tools com
`@mcp.tool()` **dentro** dela (o `mcp` chega por parâmetro; nunca importe um global):

```python
# tools/exemplo.py
from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def minha_tool(x: str) -> dict:
        """O que faz e quando o LLM deve chamar."""
        return {"ok": True, "eco": x[:100]}
```

Oficial: adicione `exemplo` em `ENABLED_TOOLS` ou em `config.yaml` e reinicie.
Personalizada: basta o arquivo estar em `custom_tools/` e reiniciar.
Exemplo comentado (tool `eco`) em `exemplos/custom_tools/exemplo.py`; para testar:
`cp exemplos/custom_tools/exemplo.py custom_tools/` e reinicie.

`custom_tools/` é só local: está no `.gitignore` e no `.dockerignore`, então não vai para o
repositório nem para a imagem; cada servidor monta o seu como volume. Tudo nele é tratado
como tool personalizada. Segredo de tool personalizada vem do ambiente (`.env` ou
Infisical), nunca do arquivo.

Personalizadas podem importar helpers próprios (`custom_tools/_util.py` →
`from custom_tools._util import ...`) e os oficiais (`from tools._comum import TZ`).
Arquivos com `_` no início nunca viram plugin.

Comportamento do loader:

- Import ou `register()` com erro → plugin logado com o motivo e ignorado; os demais sobem.
  Tools de um `register()` que falhou no meio não ficam registradas pela metade.
- Duas tools com o mesmo nome → `ColisaoDeTools` no boot, citando os dois módulos
  (o FastMCP sozinho manteria a primeira em silêncio). Vale também entre oficial e personalizada.

Regras:

- Nome e docstring claros: é isso que o LLM lê para decidir quando chamar.
- Retorno pequeno (< ~1 KB) e sem segredos.
- Entrada vem de **voz** = não confiável. Tool que altera estado → whitelist de parâmetros.
- Nada de `eval`/`exec` (há teste que verifica); conta usa `simpleeval`.
- Log em **stderr** (stdout é o canal do protocolo).

## Testes

```bash
pip install -r requirements-dev.txt
pytest -q
```

Sem rede: inclui um teste de ponta a ponta com WebSocket fake em 127.0.0.1
(`initialize` → `tools/list` → `tools/call` passando pelo `pipe.py`).

## Segurança

- A URL do endpoint é credencial: quem a tem injeta tools no seu agente. Vazou → gere outra no console.
- O pipe mascara o token nos logs.
- Com Infisical, o `.env` guarda só client-id/secret da machine identity + `INFISICAL_PROJECT_ID`:
  eles dão acesso a todos os segredos do ambiente, então dê à identity permissão só de leitura
  e só no ambiente/pasta necessários. O secret não chega ao processo das tools.
- Só roda código de `tools/`/`custom_tools/` que você habilitou por nome; nomes são validados
  por regex antes do import (sem path traversal). Personalizada nunca substitui oficial de
  mesmo nome. Em container, `custom_tools/` é montado `:ro` e o processo roda como non-root
  (uid 10001).
- Plugin é código Python com os mesmos privilégios do servidor: revise antes de habilitar.
- Log sempre em stderr; stdout é exclusivo do protocolo MCP.
- `mcp<2` fixado: o SDK 2.x renomeou `FastMCP` para `MCPServer`.
