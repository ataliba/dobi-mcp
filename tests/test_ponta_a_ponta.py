"""WebSocket fake em 127.0.0.1 <-> pipe.py <-> server.py: initialize, tools/list, tools/call."""
import asyncio
import json
import os
import subprocess
import sys

from websockets.asyncio.server import serve

from conftest import RAIZ

TIMEOUT = 30


async def _roteiro(ws, resultado: dict) -> None:
    async def pedir(id_, method, params):
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params}))
        while True:  # ignora notificações (ex.: logs) até chegar a resposta com este id
            msg = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT))
            if msg.get("id") == id_:
                return msg

    resultado["init"] = await pedir(1, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "teste", "version": "0"}})
    await ws.send(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    resultado["list"] = await pedir(2, "tools/list", {})
    resultado["call"] = await pedir(3, "tools/call",
                                    {"name": "calcular", "arguments": {"expressao": "2**10"}})


async def _executar() -> tuple[dict, str]:
    resultado: dict = {}
    pronto = asyncio.Event()

    async def handler(ws):
        try:
            await _roteiro(ws, resultado)
        finally:
            pronto.set()

    async with serve(handler, "127.0.0.1", 0) as servidor:
        porta = servidor.sockets[0].getsockname()[1]
        env = {**os.environ, "MCP_ENDPOINT": f"ws://127.0.0.1:{porta}/mcp/?token=segredo",
               "ENABLED_TOOLS": "calculo,tempo"}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(RAIZ / "pipe.py"), str(RAIZ / "server.py"),
            env=env, cwd=RAIZ, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            await asyncio.wait_for(pronto.wait(), TIMEOUT)
        finally:
            proc.terminate()
            _, err = await proc.communicate()
    return resultado, err.decode()


def test_initialize_list_call_via_pipe():
    r, stderr = asyncio.run(_executar())

    assert r["init"]["result"]["serverInfo"]["name"] == "dobi-mcp", stderr
    assert {t["name"] for t in r["list"]["result"]["tools"]} == {"calcular", "data_hora"}

    call = r["call"]["result"]
    assert not call.get("isError")
    assert json.loads(call["content"][0]["text"]) == {"ok": True, "resultado": 1024}
    assert len(json.dumps(call)) < 1024

    assert "tools ativas (2): calculo, tempo" in stderr
    assert "segredo" not in stderr  # token mascarado no log


async def _sigterm() -> tuple[int | None, int, str]:
    """Pipe conectado recebe SIGTERM (como no `docker stop`): deve mandar close frame e sair."""
    conectou, fechou = asyncio.Event(), asyncio.Event()
    codigo: dict = {}

    async def handler(ws):
        conectou.set()
        try:
            await ws.wait_closed()
        finally:
            codigo["close"] = ws.close_code
            fechou.set()

    async with serve(handler, "127.0.0.1", 0) as servidor:
        porta = servidor.sockets[0].getsockname()[1]
        env = {**os.environ, "MCP_ENDPOINT": f"ws://127.0.0.1:{porta}/mcp/?token=segredo",
               "ENABLED_TOOLS": "calculo"}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(RAIZ / "pipe.py"), str(RAIZ / "server.py"),
            env=env, cwd=RAIZ, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            await asyncio.wait_for(conectou.wait(), TIMEOUT)
            await asyncio.sleep(0.5)  # deixa o handler de sinal ser instalado e o server.py subir
            proc.terminate()
            await asyncio.wait_for(fechou.wait(), 10)
            _, err = await asyncio.wait_for(proc.communicate(), 10)
        finally:
            if proc.returncode is None:
                proc.kill()
    return codigo.get("close"), proc.returncode, err.decode()


def test_sigterm_fecha_websocket_com_close_frame():
    close, rc, stderr = asyncio.run(_sigterm())
    assert close == 1001, stderr  # "going away" limpo; não 1006 (caiu) nem 1011 (erro)
    assert rc == 0, stderr
    assert "recebido SIGTERM, fechando túnel" in stderr
    assert "encerrado por sinal" in stderr
