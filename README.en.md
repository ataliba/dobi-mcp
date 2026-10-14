# dobi-mcp

[Português](README.md) | **English**

Minimal MCP server for **XiaoZhi** agents (e.g. the Dobi robot). Exposes read-only tools
and connects to the XiaoZhi cloud through an **outbound** WebSocket — no open ports on your side.

```
XiaoZhi cloud (wss) <──> pipe.py (bridge) <──stdio──> server.py (FastMCP)
```

## Tools

| Tool | What it does |
|---|---|
| `calcular` | Math expressions via `simpleeval` (no `eval`, no RCE) |
| `data_hora` | Current date/time in America/Sao_Paulo |
| `status_servidor` | Host CPU, memory, disk and uptime |
| `proximos_feriados` | Upcoming national/state holidays in Brazil ([feriadosapi.com](https://feriadosapi.com)) |
| `dia_util_bancario` | Whether a date is a Brazilian banking business day, and the next one |
| `clima` | Current weather and up to 7-day forecast by city ([Open-Meteo](https://open-meteo.com), no API key) |

Tool names and replies are in Portuguese: they are spoken by the robot.

Custom tools: whatever is in `custom_tools/` (local, outside git; see below).

## Running

1. Get the endpoint: xiaozhi.me/console/agents → Configure role → **MCP Endpoint** (bottom right).
2. Run:

```bash
pip install -r requirements.txt
export MCP_ENDPOINT='wss://api.xiaozhi.me/mcp/?token=...'   # single quotes!
python pipe.py server.py
```

Holidays: create a free account at feriadosapi.com, generate a token in the dashboard and export
`FERIADOS_API_KEY` (optionally `FERIADOS_UF=SP` as the default state).

Weather: Open-Meteo is free and needs no key; `CLIMA_CIDADE=Campinas` sets the default city (optional).

Or in a container (non-root, uid 10001). Official tools ship inside the image; custom tools
come in through a read-only volume at `/app/custom_tools`:

```bash
docker compose up -d --build          # uses the sample docker-compose.yml
# or, without compose:
docker build -t dobi-mcp .
docker run -d --name dobi-mcp --restart unless-stopped --env-file .env \
  -e ENABLED_TOOLS=calculo,tempo,sistema,feriados,clima \
  -v "$PWD/custom_tools:/app/custom_tools:ro" dobi-mcp
```

Files in `custom_tools/` must be readable by uid 10001 (`chmod o+r custom_tools/*.py`).
Changed an official tool? Rebuild the image. Changed a custom one? Just restart the container.

Success = log line `conectado em wss://api.xiaozhi.me/mcp/?token=***`. Then ask the robot
"quanto é 2 elevado a 10?", "como está o servidor?" or "vai chover amanhã em Campinas?".

## Secrets via Infisical (optional)

`USE_INFISICAL` turns [Infisical](https://infisical.com) on/off as the secrets source
(`MCP_ENDPOINT`, `FERIADOS_API_KEY`, `FERIADOS_UF`):

- **Off** (default: unset or `0`): secrets come from the environment/`.env`, as above.
- **On** (`1`, `true`, `yes`, `on` or `sim`): `pipe.py` re-executes itself under
  `infisical run` and the project secrets are injected into the environment first.

| Variable | Purpose |
|---|---|
| `USE_INFISICAL` | On/off |
| `INFISICAL_ENV` | Environment (`dev`, `staging`, `prod`); unset = CLI default (`dev`!) |
| `INFISICAL_PROJECT_ID` | Project ID; required without `.infisical.json` (e.g. container) |
| `INFISICAL_PATH` | Secrets folder in the project (default `/`) |
| `INFISICAL_API_URL` | Self-hosted instance; becomes `--domain` on login and run |
| `INFISICAL_UNIVERSAL_AUTH_CLIENT_ID` / `_SECRET` | Machine identity (container/CI) — recommended |
| `INFISICAL_TOKEN` | Static token (legacy); ignored when client-id/secret are set |

Only the variables that are set become flags (`--env`, `--projectId`, `--path`, `--domain`).
At boot, `segredos via Infisical (env=..., sessão Universal Auth)` is logged to stderr.

**Universal Auth session** (same approach as [velhodorio](#origins)): with client-id/secret in the environment, `pipe.py` runs
`infisical login --method=universal-auth --silent --plain` on every boot, takes the short-lived
access token and only then runs `infisical run` with it. No static token expiring in `.env`:
restart, new session. Client-id/secret reach the CLI through the environment (not as arguments,
so they don't show up in `ps`) and the secret is removed from the environment before the server
and tools start. Login failed → the container exits with the CLI error (secret masked) and
`restart: unless-stopped` tries again.

**Local** (CLI installed, user login):

```bash
infisical login
infisical init                              # once; creates .infisical.json
USE_INFISICAL=1 INFISICAL_ENV=dev python pipe.py server.py
```

**Container** (machine identity): the Infisical CLI already ships in the image; only using it
is optional (`USE_INFISICAL`). Create a machine identity with Universal Auth (read-only, limited
to the needed environment/folder) and put only what is needed to authenticate in `.env`:

```bash
# .env
INFISICAL_UNIVERSAL_AUTH_CLIENT_ID=...
INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET=...
INFISICAL_PROJECT_ID=...
INFISICAL_API_URL=https://infisical.example.com   # if self-hosted
```

```bash
USE_INFISICAL=1 docker compose up -d --build
# or, without compose:
docker build -t dobi-mcp .
docker run -d --name dobi-mcp --restart unless-stopped --env-file .env \
  -e USE_INFISICAL=1 -e INFISICAL_ENV=prod \
  -e ENABLED_TOOLS=calculo,tempo,sistema,feriados,clima \
  -v "$PWD/custom_tools:/app/custom_tools:ro" dobi-mcp
```

In compose, `INFISICAL_ENV` defaults to `prod`.

Common errors:

- ``USE_INFISICAL ativo, mas o CLI `infisical` não está no PATH`` → install the CLI
  (the image already has it), or turn it off with `USE_INFISICAL=0`.
- `Please either run infisical init ... or pass in project id with --projectId flag` →
  run `infisical init` or set `INFISICAL_PROJECT_ID`.
- `login Universal Auth falhou (código 1): ...` → wrong client-id/secret, identity without
  Universal Auth, or `INFISICAL_API_URL` pointing to the wrong instance.
- Starts but secrets are missing → unset `INFISICAL_ENV` falls back to `dev`; the identity needs
  access to the environment where the secrets live (usually `prod`).

## Enabling tools

Two tool sources:

| Source | Folder | Where it lives |
|---|---|---|
| Official | `tools/` | Inside the image (versioned with the project) |
| Custom | `CUSTOM_TOOLS_DIR` (default `custom_tools/`; container: `/app/custom_tools`) | Volume you mount |

- **Official:** none starts just by existing in `tools/`; activation is explicit (below).
- **Custom:** being in the folder = being active. To disable one, remove the file (or rename it
  to start with `_`).

Active official tools:

1. `ENABLED_TOOLS` (env, comma-separated), e.g. `ENABLED_TOOLS=calculo,tempo`;
2. if unset or empty, `config.yaml` → `enabled_tools` key.

Official tools outside the list are **not imported**. A listed name without a file → warning,
no crash. A custom tool with the same name as an official one → ignored with a warning, even if
the official one is disabled (a custom tool never impersonates an official one). Missing custom
folder → only official tools start.
Names must match `^[a-z][a-z0-9_]*$` (blocks `../something`; `_` helpers never load).

At boot, a one-line inventory goes to stderr:

```
tools ativas (3): calculo, tempo, custom/minha_tool | ignoradas: '../x' (nome inválido), feriados (não habilitada)
```

## Writing a tool

Official in `tools/<name>.py`, custom in `custom_tools/<name>.py` (no `__init__.py`; same
format for both). The file exports `register(mcp) -> None` and registers its tools with
`@mcp.tool()` **inside** it (`mcp` comes in as a parameter; never import a global):

```python
# tools/exemplo.py
from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def minha_tool(x: str) -> dict:
        """What it does and when the LLM should call it."""
        return {"ok": True, "eco": x[:100]}
```

Official: add `exemplo` to `ENABLED_TOOLS` or `config.yaml` and restart.
Custom: the file just needs to be in `custom_tools/`; restart.
A commented example (tool `eco`) lives in `exemplos/custom_tools/exemplo.py`; to try it:
`cp exemplos/custom_tools/exemplo.py custom_tools/` and restart.

`custom_tools/` is local only: it is in `.gitignore` and `.dockerignore`, so it goes neither to
the repository nor into the image; each server mounts its own as a volume. Everything in it is
treated as a custom tool. Custom tool secrets come from the environment (`.env` or Infisical),
never from the file.

Custom tools can import their own helpers (`custom_tools/_util.py` →
`from custom_tools._util import ...`) and the official ones (`from tools._comum import TZ`).
Files starting with `_` never become plugins.

Loader behavior:

- Import or `register()` error → plugin logged with the reason and skipped; the others start.
  Tools from a `register()` that failed midway are not left half-registered.
- Two tools with the same name → `ColisaoDeTools` at boot, naming both modules
  (FastMCP alone would silently keep the first). Also applies between official and custom.

Rules:

- Clear name and docstring: that is what the LLM reads to decide when to call it.
- Small return value (< ~1 KB), no secrets.
- Input comes from **voice** = untrusted. Tools that change state → whitelist parameters.
- No `eval`/`exec` (a test checks it); math uses `simpleeval`.
- Log to **stderr** (stdout is the protocol channel).

## Tests

```bash
python -m venv venv && . venv/bin/activate   # isolates dependencies (simpleeval, mcp...)
pip install -r requirements-dev.txt
pytest -q
```

No network needed: includes an end-to-end test with a fake WebSocket on 127.0.0.1
(`initialize` → `tools/list` → `tools/call` through `pipe.py`).

## Security

- The endpoint URL is a credential: whoever has it can inject tools into your agent. Leaked →
  generate a new one in the console.
- The pipe masks the token in logs.
- With Infisical, `.env` holds only the machine identity client-id/secret + `INFISICAL_PROJECT_ID`:
  they grant access to every secret in the environment, so give the identity read-only access
  limited to the needed environment/folder. The secret never reaches the tools process.
- Only code from official tools enabled by name and from what you put in `custom_tools/` runs;
  names are regex-validated before import (no path traversal). A custom tool never replaces an
  official one with the same name. In a container, `custom_tools/` is mounted `:ro` and the
  process runs as non-root (uid 10001).
- A plugin is Python code with the same privileges as the server: review it before enabling.
- Always log to stderr; stdout is reserved for the MCP protocol.
- `mcp<2` pinned: SDK 2.x renamed `FastMCP` to `MCPServer`.

## Origins

Velhodorio and Neuroaion, mentioned in this repository and in the commit history, are tools of
mine that I use day to day:

- **velhodorio**: my personal multi-agent assistant. It was the base for some features here,
  such as the Infisical Universal Auth login with a session token on every boot (`pipe.py`).
- **Neuroaion**: my task and energy system, which exposes an MCP server. I use it with dobi as a
  local custom tool (`custom_tools/`), which is why it is not in this repository.
