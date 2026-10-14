"""tools/clima.py: geocoding + previsão Open-Meteo, com HTTP falso."""
import asyncio
import json

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from tools import clima as mod

GEO = {"results": [
    {"name": "Campinas", "latitude": 40.0, "longitude": -100.0, "country_code": "US",
     "admin1": "Kansas", "country": "Estados Unidos"},
    {"name": "Campinas", "latitude": -22.9, "longitude": -47.06, "country_code": "BR",
     "admin1": "São Paulo", "country": "Brasil"},
]}
PREVISAO = {
    "current": {"temperature_2m": 17.6, "apparent_temperature": 18.5,
                "relative_humidity_2m": 88, "weather_code": 3, "wind_speed_10m": 6.9},
    "daily": {"time": ["2026-10-14", "2026-10-15"], "weather_code": [95, 1234],
              "temperature_2m_max": [27.7, 23.6], "temperature_2m_min": [17.6, 19.0],
              "precipitation_probability_max": [76, 98]},
}


class Resp:
    def __init__(self, dados):
        self.dados = dados

    def raise_for_status(self):
        pass

    def json(self):
        return self.dados


@pytest.fixture
def http(monkeypatch):
    """httpx.get falso; devolve a lista de chamadas (url, params). `.geo` = resposta do geocoding."""
    class Chamadas(list):
        geo = GEO

    chamadas = Chamadas()

    def get(url, params=None, timeout=None):
        chamadas.append((url, params))
        if url == mod.GEO_URL:
            return Resp(chamadas.geo)
        return Resp(PREVISAO)

    monkeypatch.setattr(mod.httpx, "get", get)
    monkeypatch.setattr(mod, "_cache_geo", {})
    monkeypatch.setattr(mod, "_cache_previsao", {})
    monkeypatch.setattr(mod, "CLIMA_CIDADE_PADRAO", "")
    return chamadas


def chamar(**args) -> dict:
    mcp = FastMCP("t")
    mod.register(mcp)
    r = asyncio.run(mcp.call_tool("clima", args))
    conteudo = r[0] if isinstance(r, tuple) else r
    return json.loads(conteudo[0].text)


def test_prefere_brasil_e_traduz_condicoes(http):
    r = chamar(cidade="Campinas, SP", dias=2)
    assert r["ok"] and r["cidade"] == "Campinas" and r["estado"] == "São Paulo"
    assert r["agora"]["temperatura_c"] == 17.6 and r["agora"]["condicao"] == "nublado"
    assert [d["condicao"] for d in r["previsao"]] == ["trovoada", "desconhecida"]
    assert r["previsao"][0] == {"data": "14/10/2026", "dia_semana": "quarta",
                                "condicao": "trovoada", "max_c": 27.7, "min_c": 17.6,
                                "chance_chuva_pct": 76}
    assert http[0][1]["name"] == "Campinas"  # ", SP" fica fora da busca
    assert http[1][1]["latitude"] == -22.9 and http[1][1]["forecast_days"] == 2


def test_cache_evita_nova_chamada(http):
    chamar(cidade="Campinas")
    chamar(cidade="campinas")
    assert len(http) == 2


def test_dias_limitados(http):
    chamar(cidade="Campinas", dias=99)
    assert http[-1][1]["forecast_days"] == 7


def test_sem_cidade(http):
    assert chamar() == {"ok": False, "erro": "informe a cidade (ou configure CLIMA_CIDADE)"}
    assert http == []


def test_cidade_padrao(http, monkeypatch):
    monkeypatch.setattr(mod, "CLIMA_CIDADE_PADRAO", "Campinas")
    assert chamar()["cidade"] == "Campinas"


def test_cidade_inexistente(http):
    http.geo = {}
    r = chamar(cidade="Xyzzyville")
    assert r == {"ok": False, "erro": "cidade não encontrada: Xyzzyville"}


def test_falha_de_rede_vira_erro(monkeypatch):
    def explode(*a, **k):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(mod.httpx, "get", explode)
    monkeypatch.setattr(mod, "_cache_geo", {})
    r = chamar(cidade="Campinas")
    assert r == {"ok": False, "erro": "sem rede"}
