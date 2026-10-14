"""tools/busca_web.py: Brave com fallback para DuckDuckGo, com HTTP e DDGS falsos."""
import asyncio
import json

import httpx
import pytest
from ddgs.exceptions import DDGSException
from mcp.server.fastmcp import FastMCP

from tools import busca_web as mod

BRAVE = {"web": {"results": [
    {"title": "Taxa <strong>Selic</strong>", "url": "https://bcb.gov.br/selic",
     "description": "A <strong>Selic</strong> é a taxa básica de juros."},
    {"title": "Copom", "url": "https://bcb.gov.br/copom", "description": None},
]}}
DDG = [{"title": "Selic hoje", "href": "https://exemplo.com/selic", "body": "Taxa atual."}]


class Resp:
    def __init__(self, dados, status=200):
        self.dados, self.status = dados, status

    def raise_for_status(self):
        if self.status >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status}", request=None, response=None)

    def json(self):
        return self.dados


@pytest.fixture
def falsos(monkeypatch):
    """Brave e DDGS falsos. `.brave` / `.ddg` = resposta (ou exceção) de cada um."""
    class Estado:
        brave = Resp(BRAVE)
        ddg = DDG
        chamadas: list = []

    est = Estado()
    est.chamadas = []

    def get(url, headers=None, params=None, timeout=None):
        est.chamadas.append(("brave", headers, params))
        return est.brave

    class DDGSFalso:
        def __init__(self, timeout=None):
            pass

        def text(self, consulta, region=None, max_results=None):
            est.chamadas.append(("ddg", consulta, region, max_results))
            if isinstance(est.ddg, Exception):
                raise est.ddg
            return est.ddg

    monkeypatch.setattr(mod.httpx, "get", get)
    monkeypatch.setattr(mod, "DDGS", DDGSFalso)
    monkeypatch.setattr(mod, "BRAVE_API_KEY", "chave")
    return est


def chamar(**args) -> dict:
    mcp = FastMCP("t")
    mod.register(mcp)
    r = asyncio.run(mcp.call_tool("busca_web", args))
    conteudo = r[0] if isinstance(r, tuple) else r
    return json.loads(conteudo[0].text)


def test_brave_com_chave_limpa_html(falsos):
    r = chamar(consulta="selic", quantidade=2)
    assert r["ok"] and r["fonte"] == "brave"
    assert r["resultados"] == [
        {"titulo": "Taxa Selic", "url": "https://bcb.gov.br/selic",
         "resumo": "A Selic é a taxa básica de juros."},
        {"titulo": "Copom", "url": "https://bcb.gov.br/copom", "resumo": ""},
    ]
    _, headers, params = falsos.chamadas[0]
    assert headers["X-Subscription-Token"] == "chave"
    assert params["q"] == "selic" and params["count"] == 2


def test_sem_chave_vai_direto_ao_duckduckgo(falsos, monkeypatch):
    monkeypatch.setattr(mod, "BRAVE_API_KEY", "")
    r = chamar(consulta="selic")
    assert r == {"ok": True, "fonte": "duckduckgo", "consulta": "selic", "resultados": [
        {"titulo": "Selic hoje", "url": "https://exemplo.com/selic", "resumo": "Taxa atual."}]}
    assert [c[0] for c in falsos.chamadas] == ["ddg"]


def test_brave_falha_cai_para_duckduckgo(falsos):
    falsos.brave = Resp({}, status=429)
    r = chamar(consulta="selic")
    assert r["ok"] and r["fonte"] == "duckduckgo"
    assert [c[0] for c in falsos.chamadas] == ["brave", "ddg"]


def test_os_dois_falham(falsos):
    falsos.brave = Resp({}, status=500)
    falsos.ddg = DDGSException("ratelimit")
    r = chamar(consulta="selic")
    assert r == {"ok": False, "erro": "brave: HTTP 500; duckduckgo: ratelimit"}


def test_duckduckgo_sem_resultados_e_lista_vazia(falsos, monkeypatch):
    monkeypatch.setattr(mod, "BRAVE_API_KEY", "")
    falsos.ddg = DDGSException("No results found.")
    assert chamar(consulta="xyzzy")["resultados"] == []


def test_quantidade_limitada(falsos):
    chamar(consulta="selic", quantidade=99)
    assert falsos.chamadas[0][2]["count"] == mod.MAX_RESULTADOS


def test_consulta_vazia(falsos):
    assert chamar(consulta="  ") == {"ok": False, "erro": "informe o que pesquisar"}
    assert falsos.chamadas == []
