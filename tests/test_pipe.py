"""Helpers do pipe.py que não dependem de rede."""
import base64
import json

from pipe import agente_do_token, mascarar


def _jwt(payload: dict) -> str:
    corpo = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"eyJhbGciOiJFUzI1NiJ9.{corpo}.assinatura"


def test_agente_do_token_le_agent_id():
    url = f"wss://api.xiaozhi.me/mcp/?token={_jwt({'userId': 1, 'agentId': 2477073})}"
    assert agente_do_token(url) == "2477073"


def test_agente_do_token_cai_para_endpoint_id():
    url = f"wss://api.xiaozhi.me/mcp/?token={_jwt({'endpointId': 'agent_9'})}"
    assert agente_do_token(url) == "agent_9"


def test_agente_do_token_tolera_token_estranho():
    for url in ("wss://x/mcp/", "wss://x/mcp/?token=", "wss://x/mcp/?token=abc",
                "wss://x/mcp/?token=a.%%%.c", f"wss://x/mcp/?token=a.{base64.b64encode(b'[1]').decode()}.c"):
        assert agente_do_token(url) is None, url


def test_log_nao_vaza_token():
    token = _jwt({"agentId": 7})
    assert token not in mascarar(f"wss://x/mcp/?token={token}")
