"""tools/finlynq.py: validação de entrada de voz, confirmação e tratamento de respostas."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from tools import finlynq as mod

URL = "http://finlynq.lan:3000/api/mcp"


@pytest.fixture
def fin(monkeypatch):
    """Carrega o plugin com _chamar falso; devolve (mcp, chamadas, módulo, falso)."""
    monkeypatch.setenv("FINLYNQ_URL", URL)
    monkeypatch.setenv("FINLYNQ_TOKEN", "pf_teste")
    chamadas = []

    async def falso(url, token, tool, args):
        chamadas.append((url, token, tool, args))
        return falso.resposta

    falso.resposta = {"ok": True}
    monkeypatch.setattr(mod, "_chamar", falso)
    mcp = FastMCP("t")
    mod.register(mcp)
    return mcp, chamadas, mod, falso


def chamar(mcp, nome, **args) -> dict:
    r = asyncio.run(mcp.call_tool(nome, args))
    conteudo = r[0] if isinstance(r, tuple) else r
    return json.loads(conteudo[0].text)


@pytest.mark.parametrize("ausente,msg", [("FINLYNQ_URL", "FINLYNQ_URL ausente"),
                                         ("FINLYNQ_TOKEN", "FINLYNQ_TOKEN ausente")])
def test_sem_config_nao_registra(monkeypatch, ausente, msg):
    monkeypatch.setenv("FINLYNQ_URL", URL)
    monkeypatch.setenv("FINLYNQ_TOKEN", "pf_teste")
    monkeypatch.delenv(ausente)
    with pytest.raises(RuntimeError, match=msg):
        mod.register(FastMCP("t"))


def test_tools_expostas(fin):
    mcp, *_ = fin
    nomes = {t.name for t in asyncio.run(mcp.list_tools())}
    assert nomes == {"finlynq_saldos", "finlynq_patrimonio", "finlynq_categorias",
                     "finlynq_buscar_transacoes", "finlynq_registrar_transacao",
                     "finlynq_apagar_transacao"}


def test_saldos_enxutos(fin):
    mcp, chamadas, _, falso = fin
    falso.resposta = {
        "accounts": [{"id": 3, "name": "Nubank", "balance": 120.5, "currency": "BRL",
                      "balanceTagged": {"amount": 120.5}, "basis": "ledger"}],
        "reportingCurrency": "BRL", "totalReporting": {"amount": 120.5, "currency": "BRL"}}
    assert chamar(mcp, "finlynq_saldos") == {
        "contas": [{"id": 3, "nome": "Nubank", "saldo": 120.5, "moeda": "BRL"}],
        "total": 120.5, "moeda_total": "BRL"}
    assert chamadas == [(URL, "pf_teste", "get_account_balances", {})]


def test_busca_normaliza_e_enxuga(fin):
    mcp, chamadas, _, falso = fin
    falso.resposta = {"results": [{"id": 9, "date": "2026-10-30", "payee": "Padaria",
                                   "amount": -12.0, "currency": "BRL", "account": "Nubank",
                                   "category": None, "createdAt": "x"}], "count": 1}
    r = chamar(mcp, "finlynq_buscar_transacoes", favorecido="  padaria ", data_inicio="2026-10-01")
    assert r == {"transacoes": [{"id": 9, "data": "2026-10-30", "favorecido": "Padaria",
                                 "valor": -12.0, "moeda": "BRL", "conta": "Nubank"}], "total": 1}
    assert chamadas[0][2:] == ("search_transactions",
                               {"payee": "padaria", "start_date": "2026-10-01", "limit": 5})


@pytest.mark.parametrize("tool,args,trecho", [
    ("finlynq_buscar_transacoes", {"limite": 500}, "limite deve ser"),
    ("finlynq_buscar_transacoes", {"data_fim": "ontem"}, "AAAA-MM-DD"),
    ("finlynq_registrar_transacao", {"valor": -5, "favorecido": "x", "conta": "c"}, "positivo"),
    ("finlynq_registrar_transacao", {"valor": 0, "favorecido": "x", "conta": "c"}, "positivo"),
    ("finlynq_registrar_transacao", {"valor": 1e9, "favorecido": "x", "conta": "c"}, "até"),
    ("finlynq_registrar_transacao", {"valor": 5, "favorecido": " ", "conta": "c"}, "favorecido vazio"),
    ("finlynq_registrar_transacao", {"valor": 5, "favorecido": "x", "conta": ""}, "conta vazio"),
    ("finlynq_registrar_transacao", {"valor": 5, "favorecido": "x", "conta": "c", "tipo": "pix"}, "tipo deve ser"),
    ("finlynq_registrar_transacao", {"valor": 5, "favorecido": "x", "conta": "c", "data": "2026-02-30"}, "AAAA-MM-DD"),
    ("finlynq_apagar_transacao", {"transacao_id": 0, "favorecido": "x", "valor": -1, "confirmar": True}, "transacao_id"),
    ("finlynq_apagar_transacao", {"transacao_id": 1, "favorecido": "x", "valor": 0, "confirmar": True}, "diferente de zero"),
])
def test_entrada_invalida_nao_chama_remoto(fin, tool, args, trecho):
    mcp, chamadas, *_ = fin
    r = chamar(mcp, tool, **args)
    assert trecho in r["erro"]
    assert chamadas == []


def test_registrar_sem_confirmar_e_simulacao(fin):
    mcp, chamadas, *_ = fin
    r = chamar(mcp, "finlynq_registrar_transacao", valor=50, favorecido="Mercado", conta="Nubank")
    assert r["simulacao"] is True
    assert chamadas[0][2:] == ("manage_transactions", {
        "op": "record", "amount": -50.0, "payee": "Mercado", "account": "Nubank", "dryRun": True})


def test_registrar_confirmado_receita(fin):
    mcp, chamadas, *_ = fin
    r = chamar(mcp, "finlynq_registrar_transacao", valor=1000.456, favorecido="Salário",
               conta="Itaú", tipo="Receita", categoria="Salário", data="2026-10-05", confirmar=True)
    assert "simulacao" not in r
    assert chamadas[0][3] == {"op": "record", "amount": 1000.46, "payee": "Salário", "account": "Itaú",
                              "category": "Salário", "date": "2026-10-05", "dryRun": False}


def test_apagar_sem_confirmar_nao_chama_remoto(fin):
    mcp, chamadas, *_ = fin
    r = chamar(mcp, "finlynq_apagar_transacao", transacao_id=9, favorecido="Padaria", valor=-12)
    assert r["simulacao"] is True and r["apagaria"] == {"id": 9, "payee": "Padaria", "amount": -12.0}
    assert chamadas == []


def test_apagar_confirmado_manda_expected(fin):
    mcp, chamadas, *_ = fin
    chamar(mcp, "finlynq_apagar_transacao", transacao_id=9, favorecido="Padaria", valor=-12,
           confirmar=True)
    assert chamadas[0][2:] == ("manage_transactions", {
        "op": "delete", "id": 9, "expected": {"payee": "Padaria", "amount": -12.0}})


def test_erro_do_finlynq_repassado(fin):
    mcp, _, _, falso = fin
    falso.resposta = {"erro": "Account \"x\" did not match"}
    r = chamar(mcp, "finlynq_registrar_transacao", valor=5, favorecido="x", conta="x")
    assert r == {"erro": "Account \"x\" did not match"}


def test_resposta_grande_truncada(fin):
    mcp, _, _, falso = fin
    falso.resposta = [{"id": i, "name": "categoria " * 5, "type": "E", "group": "g"} for i in range(80)]
    r = chamar(mcp, "finlynq_categorias")
    assert r["truncado"] is True and 0 < len(r["categorias"]) < 80


def test_falha_de_rede_vira_erro_sem_vazar_token(fin, monkeypatch, caplog):
    mcp, _, mod, _ = fin

    async def explode(url, token, tool, args):
        raise ConnectionError(f"falhou com {token}")

    monkeypatch.setattr(mod, "_chamar", explode)
    assert chamar(mcp, "finlynq_saldos") == {"erro": "Finlynq indisponível (ConnectionError)"}
    assert "pf_teste" not in caplog.text


def _texto(t):
    return SimpleNamespace(isError=False, content=[SimpleNamespace(type="text", text=t)])


@pytest.mark.parametrize("resultado,esperado", [
    (_texto('{"success": true, "data": {"a": 1}}'), {"a": 1}),
    (_texto('{"success": true, "data": [1, 2]}'), [1, 2]),
    (_texto('{"b": 2}'), {"b": 2}),
    (_texto("oi"), {"resposta": "oi"}),
    (_texto("Error: Transaction #9 not found"), {"erro": "Transaction #9 not found"}),
    (SimpleNamespace(isError=True, content=[SimpleNamespace(type="text", text="401")]), {"erro": "401"}),
])
def test_interpreta_resultado_remoto(monkeypatch, resultado, esperado):
    class Sessao:
        def __init__(self, *a):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def initialize(self):
            pass

        async def call_tool(self, tool, args):
            return resultado

    class Cliente:
        def __init__(self, url, headers, timeout):
            assert headers == {"Authorization": "Bearer t"}

        async def __aenter__(self):
            return None, None, None

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(mod, "streamablehttp_client", Cliente)
    monkeypatch.setattr(mod, "ClientSession", Sessao)
    assert asyncio.run(mod._chamar("u", "t", "x", {})) == esperado


def _erro_http(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://x/api/mcp", headers={"Authorization": "Bearer pf_teste"})
    return httpx.HTTPStatusError("erro pf_teste", request=req, response=httpx.Response(status, request=req))


@pytest.mark.parametrize("erro,motivo", [
    (lambda: ExceptionGroup("g", [_erro_http(503)]), "HTTP 503"),
    (lambda: ExceptionGroup("g", [ExceptionGroup("h", [_erro_http(401)])]), "HTTP 401"),
    (lambda: ExceptionGroup("g", [ValueError("x"), _erro_http(500)]), "HTTP 500"),
    (lambda: ExceptionGroup("g", [ConnectionError("pf_teste")]), "ConnectionError"),
    (lambda: _erro_http(502), "HTTP 502"),
])
def test_grupo_de_excecoes_revela_causa_sem_vazar_token(fin, monkeypatch, caplog, erro, motivo):
    mcp, *_ = fin

    async def explode(url, token, tool, args):
        raise erro()

    monkeypatch.setattr(mod, "_chamar", explode)
    r = chamar(mcp, "finlynq_saldos")
    assert r == {"erro": f"Finlynq indisponível ({motivo})"}
    assert motivo in caplog.text
    assert "pf_teste" not in caplog.text and "pf_teste" not in r["erro"]
