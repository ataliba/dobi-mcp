"""Ponte WebSocket <-> stdio entre o endpoint MCP do XiaoZhi e um servidor MCP local.

Uso:  MCP_ENDPOINT='wss://api.xiaozhi.me/mcp/?token=...' python pipe.py server.py

- Conexão é de saída (sem portas abertas no seu lado).
- Reconecta com backoff exponencial + jitter.
- O token nunca vai para o log.
- USE_INFISICAL=1 -> reexecuta sob `infisical run` (segredos injetados no ambiente).
  Com INFISICAL_UNIVERSAL_AUTH_CLIENT_ID/SECRET (machine identity), faz antes o login
  Universal Auth e usa o token de sessão gerado a cada boot (não vence parado no .env).
"""
import asyncio
import logging
import os
import random
import shutil
import subprocess
import sys

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [pipe] %(message)s")
log = logging.getLogger("pipe")

BACKOFF_INICIAL, BACKOFF_MAX = 1, 60
VERDADEIRO = {"1", "true", "yes", "on", "sim"}
# Marca que já estamos dentro do `infisical run` (evita reexecutar em loop)
SENTINELA = "DOBI_SOB_INFISICAL"
UA_ID, UA_SECRET = "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID", "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET"


class ErroInfisical(RuntimeError):
    """Falha no login Universal Auth (mensagem já segura para log)."""


def comando_infisical(env: dict, argv: list[str]) -> list[str] | None:
    """Comando para reexecutar sob `infisical run`, ou None se não for o caso.

    Opcionais: INFISICAL_ENV (dev/staging/prod), INFISICAL_PROJECT_ID (obrigatório com
    machine identity), INFISICAL_PATH, INFISICAL_API_URL (instância própria -> --domain).
    Sem eles, vale o .infisical.json.
    """
    if env.get("USE_INFISICAL", "").strip().lower() not in VERDADEIRO or env.get(SENTINELA):
        return None
    cmd = ["infisical", "run", "--silent"]
    for var, flag in (("INFISICAL_ENV", "--env"), ("INFISICAL_PROJECT_ID", "--projectId"),
                      ("INFISICAL_PATH", "--path"), ("INFISICAL_API_URL", "--domain")):
        if env.get(var):
            cmd.append(f"{flag}={env[var]}")
    return [*cmd, "--", sys.executable, *argv]


def usa_universal_auth(env: dict) -> bool:
    return bool(env.get(UA_ID, "").strip() and env.get(UA_SECRET, "").strip())


def comando_login(env: dict) -> list[str]:
    """`infisical login` Universal Auth. Client-id/secret vão pelo ambiente (o CLI lê
    INFISICAL_UNIVERSAL_AUTH_CLIENT_*), nunca por argumento: não aparecem no `ps`."""
    cmd = ["infisical", "login", "--method=universal-auth", "--silent", "--plain"]
    if env.get("INFISICAL_API_URL"):
        cmd.append(f"--domain={env['INFISICAL_API_URL']}")
    return cmd


def token_de_sessao(env: dict, executar=subprocess.run) -> str:
    """Troca client-id/secret por um token de acesso de curta duração."""
    try:
        r = executar(comando_login(env), env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ErroInfisical(f"login Universal Auth falhou: {type(e).__name__}") from None
    token = (r.stdout or "").strip().splitlines()[-1:] if r.returncode == 0 else []
    if not token or not token[0].strip():
        detalhe = (r.stderr or "").strip().replace(env.get(UA_SECRET, "") or "\0", "***")
        raise ErroInfisical(f"login Universal Auth falhou (código {r.returncode}): {detalhe[-300:]}")
    return token[0].strip()


def mascarar(url: str) -> str:
    return url.split("?")[0] + "?token=***" if "?" in url else url


async def sessao(endpoint: str, script: str) -> None:
    async with websockets.connect(endpoint, ping_interval=20, ping_timeout=20,
                                  max_size=2**20) as ws:
        log.info("conectado em %s", mascarar(endpoint))
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=None,  # stderr do server vai direto para o terminal/log
            limit=2**20,
        )

        async def ws_para_proc():
            async for msg in ws:
                if isinstance(msg, bytes):
                    msg = msg.decode()
                proc.stdin.write(msg.encode() + b"\n")
                await proc.stdin.drain()

        async def proc_para_ws():
            while line := await proc.stdout.readline():
                await ws.send(line.decode().rstrip("\n"))

        tarefas = [asyncio.create_task(ws_para_proc()), asyncio.create_task(proc_para_ws())]
        try:
            done, _ = await asyncio.wait(tarefas, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if t.exception():
                    raise t.exception()
        finally:
            for t in tarefas:
                t.cancel()
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except asyncio.TimeoutError:
                    proc.kill()


def talvez_infisical() -> None:
    cmd = comando_infisical(os.environ, sys.argv)
    if cmd is None:
        return
    if not shutil.which("infisical"):
        sys.exit("USE_INFISICAL ativo, mas o CLI `infisical` não está no PATH")
    env = dict(os.environ)
    auth = "token do ambiente"
    if usa_universal_auth(env):
        try:
            env["INFISICAL_TOKEN"] = token_de_sessao(env)
        except ErroInfisical as e:
            sys.exit(str(e))
        auth = "sessão Universal Auth"
    # credencial longa não desce para o servidor/tools: só o token de sessão segue
    env.pop(UA_SECRET, None)
    env[SENTINELA] = "1"
    log.info("segredos via Infisical (env=%s, %s)", env.get("INFISICAL_ENV") or "padrão", auth)
    os.execvpe(cmd[0], cmd, env)  # não retorna


async def main() -> None:
    endpoint = os.environ.get("MCP_ENDPOINT")
    if not endpoint or len(sys.argv) != 2:
        sys.exit("uso: MCP_ENDPOINT='wss://...' python pipe.py server.py")
    script = sys.argv[1]
    backoff = BACKOFF_INICIAL
    while True:
        try:
            await sessao(endpoint, script)
            backoff = BACKOFF_INICIAL
            log.info("sessão encerrada, reconectando")
        except Exception as e:  # noqa: BLE001
            log.warning("falha: %s: %s", type(e).__name__, str(e)[:200])
        espera = min(backoff, BACKOFF_MAX) + random.uniform(0, 1)
        log.info("nova tentativa em %.1fs", espera)
        await asyncio.sleep(espera)
        backoff *= 2


if __name__ == "__main__":
    talvez_infisical()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
