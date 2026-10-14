"""Busca na web: Brave Search API se houver BRAVE_API_KEY; senão (ou se falhar) DuckDuckGo (ddgs)."""
import html
import logging
import os
import re

import httpx
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from mcp.server.fastmcp import FastMCP

log = logging.getLogger("dobi-mcp")
# ddgs (via primp) loga em INFO cada backend que tenta; com o server em INFO vira ruído
logging.getLogger("primp").setLevel(logging.WARNING)

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "").strip()
MAX_RESULTADOS = 10
_TAGS = re.compile(r"<[^>]+>")


def _limpar(texto: str | None) -> str:
    """Brave marca os termos com <strong> e escapa entidades (&gt;); o robô fala o texto puro."""
    return html.unescape(_TAGS.sub("", texto or "")).strip()


def _brave(consulta: str, n: int) -> list[dict]:
    r = httpx.get(BRAVE_URL, timeout=8,
                  headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
                  params={"q": consulta, "count": n, "country": "BR", "search_lang": "pt-br"})
    r.raise_for_status()
    return [{"titulo": _limpar(x.get("title")), "url": x.get("url"),
             "resumo": _limpar(x.get("description"))}
            for x in (r.json().get("web") or {}).get("results", [])[:n]]


def _duckduckgo(consulta: str, n: int) -> list[dict]:
    try:
        resultados = DDGS(timeout=8).text(consulta, region="br-pt", max_results=n)
    except DDGSException as e:
        if "no results" in str(e).lower():
            return []
        raise
    return [{"titulo": x.get("title", ""), "url": x.get("href"), "resumo": x.get("body", "")}
            for x in resultados[:n]]


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def busca_web(consulta: str, quantidade: int = 5) -> dict:
        """Pesquisa na internet e devolve os principais resultados (título, link e resumo).
        Use quando o usuário pedir para pesquisar, procurar ou buscar algo, perguntar sobre
        notícias, fatos recentes, preços, cotações ou qualquer coisa que você não saiba ou
        que possa ter mudado."""
        consulta = (consulta or "").strip()[:300]
        if not consulta:
            return {"ok": False, "erro": "informe o que pesquisar"}
        n = max(1, min(quantidade, MAX_RESULTADOS))
        erros = []
        if BRAVE_API_KEY:
            try:
                return {"ok": True, "fonte": "brave", "consulta": consulta,
                        "resultados": _brave(consulta, n)}
            except Exception as e:  # noqa: BLE001
                log.warning("busca_web: Brave falhou, caindo para DuckDuckGo: %s", e)
                erros.append(f"brave: {str(e)[:100]}")
        try:
            return {"ok": True, "fonte": "duckduckgo", "consulta": consulta,
                    "resultados": _duckduckgo(consulta, n)}
        except Exception as e:  # noqa: BLE001
            log.warning("busca_web: DuckDuckGo falhou: %s", e)
            erros.append(f"duckduckgo: {str(e)[:100]}")
        return {"ok": False, "erro": "; ".join(erros)}
