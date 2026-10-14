"""Clima via Open-Meteo (open-meteo.com) — grátis, sem API key. CLIMA_CIDADE = cidade padrão."""
import logging
import os
import time
from datetime import date

import httpx
from mcp.server.fastmcp import FastMCP

from tools._comum import DIAS_SEMANA

log = logging.getLogger("dobi-mcp")

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
PREVISAO_URL = "https://api.open-meteo.com/v1/forecast"
CLIMA_CIDADE_PADRAO = os.environ.get("CLIMA_CIDADE", "").strip()
CACHE_TTL = 10 * 60
_cache_geo: dict[str, dict] = {}
_cache_previsao: dict[tuple[float, float, int], tuple[float, dict]] = {}

# Códigos WMO (https://open-meteo.com/en/docs#weather_variable_documentation)
CONDICOES = {
    0: "céu limpo", 1: "predominantemente limpo", 2: "parcialmente nublado", 3: "nublado",
    45: "neblina", 48: "neblina com geada",
    51: "garoa fraca", 53: "garoa", 55: "garoa forte",
    56: "garoa congelante", 57: "garoa congelante forte",
    61: "chuva fraca", 63: "chuva", 65: "chuva forte",
    66: "chuva congelante", 67: "chuva congelante forte",
    71: "neve fraca", 73: "neve", 75: "neve forte", 77: "grãos de neve",
    80: "pancadas de chuva fracas", 81: "pancadas de chuva", 82: "pancadas de chuva fortes",
    85: "pancadas de neve", 86: "pancadas de neve fortes",
    95: "trovoada", 96: "trovoada com granizo", 99: "trovoada com granizo forte",
}


def _condicao(codigo) -> str:
    return CONDICOES.get(codigo, "desconhecida")


def _localizar(cidade: str) -> dict | None:
    """Geocoding pelo nome (ignora o que vem depois da vírgula, ex.: 'Campinas, SP').
    Prefere resultado no Brasil. Cache em memória sem expiração (cidade não muda de lugar)."""
    nome = cidade.split(",")[0].strip()
    chave = nome.casefold()
    if chave in _cache_geo:
        return _cache_geo[chave]
    r = httpx.get(GEO_URL, params={"name": nome, "count": 5, "language": "pt", "format": "json"},
                  timeout=8)
    r.raise_for_status()
    resultados = r.json().get("results") or []
    if not resultados:
        return None
    local = next((x for x in resultados if x.get("country_code") == "BR"), resultados[0])
    _cache_geo[chave] = local
    return local


def _previsao(lat: float, lon: float, dias: int) -> dict:
    chave = (round(lat, 3), round(lon, 3), dias)
    if (hit := _cache_previsao.get(chave)) and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    r = httpx.get(PREVISAO_URL, timeout=8, params={
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": dias,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max",
    })
    r.raise_for_status()
    dados = r.json()
    _cache_previsao[chave] = (time.time(), dados)
    return dados


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def clima(cidade: str = "", dias: int = 3) -> dict:
        """Tempo agora e previsão dos próximos dias (máxima, mínima, condição e chance de
        chuva) para uma cidade pelo nome, como 'Campinas' ou 'Rio de Janeiro'. Vazio = cidade
        padrão. Use quando o usuário perguntar como está o tempo, se vai chover, se vai
        fazer frio ou calor, hoje, amanhã ou nos próximos dias."""
        cidade = (cidade or CLIMA_CIDADE_PADRAO).strip()
        if not cidade:
            return {"ok": False, "erro": "informe a cidade (ou configure CLIMA_CIDADE)"}
        dias = max(1, min(dias, 7))
        try:
            local = _localizar(cidade[:80])
            if local is None:
                return {"ok": False, "erro": f"cidade não encontrada: {cidade[:80]}"}
            dados = _previsao(local["latitude"], local["longitude"], dias)
        except Exception as e:  # noqa: BLE001
            log.warning("clima falhou: %s", e)
            return {"ok": False, "erro": str(e)[:200]}
        atual, diario = dados["current"], dados["daily"]
        previsao = []
        for i, dia_iso in enumerate(diario["time"]):
            dia = date.fromisoformat(dia_iso)
            previsao.append({
                "data": dia.strftime("%d/%m/%Y"), "dia_semana": DIAS_SEMANA[dia.weekday()],
                "condicao": _condicao(diario["weather_code"][i]),
                "max_c": diario["temperature_2m_max"][i], "min_c": diario["temperature_2m_min"][i],
                "chance_chuva_pct": diario["precipitation_probability_max"][i],
            })
        return {
            "ok": True,
            "cidade": local["name"], "estado": local.get("admin1"), "pais": local.get("country"),
            "agora": {
                "temperatura_c": atual["temperature_2m"],
                "sensacao_c": atual["apparent_temperature"],
                "umidade_pct": atual["relative_humidity_2m"],
                "vento_kmh": atual["wind_speed_10m"],
                "condicao": _condicao(atual["weather_code"]),
            },
            "previsao": previsao,
        }
