"""Feriados via feriadosapi.com — token em FERIADOS_API_KEY (dashboard, plano free basta)."""
import logging
import os
import time
from datetime import date, datetime

import httpx
from mcp.server.fastmcp import FastMCP

from tools._comum import DIAS_SEMANA, TZ

log = logging.getLogger("dobi-mcp")

FERIADOS_URL = "https://feriadosapi.com/api/v1"
FERIADOS_UF_PADRAO = os.environ.get("FERIADOS_UF", "").upper()
UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
       "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}
_cache_feriados: dict[tuple[str, int], tuple[float, list]] = {}
CACHE_TTL = 6 * 3600


def _feriados_api(caminho: str, params: dict | None = None) -> dict:
    token = os.environ.get("FERIADOS_API_KEY")
    if not token:
        raise RuntimeError("FERIADOS_API_KEY não configurada")
    r = httpx.get(f"{FERIADOS_URL}{caminho}", params=params, timeout=8,
                  headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


def _feriados_do_ano(uf: str, ano: int) -> list:
    """Lista de feriados (nacionais + estaduais se uf) do ano, com cache em memória."""
    chave = (uf, ano)
    if (hit := _cache_feriados.get(chave)) and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    caminho = f"/feriados/estado/{uf}" if uf else "/feriados/nacionais"
    feriados = _feriados_api(caminho, {"ano": ano, "limit": 100})["feriados"]
    _cache_feriados[chave] = (time.time(), feriados)
    return feriados


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def proximos_feriados(uf: str = "", quantidade: int = 3) -> dict:
        """Lista os próximos feriados a partir de hoje (nacionais e, se informada a sigla
        do estado, como 'SP' ou 'RJ', também os estaduais). Use quando o usuário perguntar
        quando é o próximo feriado, se tem feriado este mês ou quantos faltam."""
        uf = (uf or FERIADOS_UF_PADRAO).strip().upper()
        if uf and uf not in UFS:
            return {"ok": False, "erro": f"UF inválida: {uf[:5]}"}
        quantidade = max(1, min(quantidade, 10))
        hoje = datetime.now(TZ).date()
        try:
            proximos = []
            for ano in (hoje.year, hoje.year + 1):
                for f in _feriados_do_ano(uf, ano):
                    dia = datetime.strptime(f["data"], "%d/%m/%Y").date()
                    if dia >= hoje:
                        proximos.append((dia, f))
                if len(proximos) >= quantidade:
                    break
        except Exception as e:  # noqa: BLE001
            log.warning("proximos_feriados falhou: %s", e)
            return {"ok": False, "erro": str(e)[:200]}
        proximos.sort(key=lambda p: p[0])
        return {"ok": True, "uf": uf or None, "feriados": [
            {"data": dia.strftime("%d/%m/%Y"), "dia_semana": DIAS_SEMANA[dia.weekday()],
             "nome": f["nome"], "tipo": f.get("tipo"), "faltam_dias": (dia - hoje).days}
            for dia, f in proximos[:quantidade]]}

    @mcp.tool()
    def dia_util_bancario(data: str = "") -> dict:
        """Verifica se uma data é dia útil bancário (não é fim de semana nem feriado
        bancário) e qual o próximo dia útil. Data no formato AAAA-MM-DD; vazio = hoje.
        Use quando o usuário perguntar se banco abre, se boleto/pix compensa num dia."""
        try:
            dia = date.fromisoformat(data) if data else datetime.now(TZ).date()
            resp = _feriados_api(f"/feriados/dia-util-bancario/{dia.isoformat()}")
        except Exception as e:  # noqa: BLE001
            log.warning("dia_util_bancario falhou: %s", e)
            return {"ok": False, "erro": str(e)[:200]}
        return {"ok": True, **{k: v for k, v in resp.items() if not isinstance(v, (dict, list))}}
