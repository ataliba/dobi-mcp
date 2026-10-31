"""Finlynq (finanças pessoais self-hosted, github.com/finlynq/finlynq) via MCP remoto.

Wrappers fixos de 5 das ~55 tools do MCP do Finlynq (streamable-http, Bearer API
key `pf_*`), as mesmas que o velhodorio usa: saldos, patrimônio, categorias, busca,
registro e remoção de transação. Entrada vem de voz: parâmetros validados, valor
sempre positivo (o sinal sai de `tipo`) e escrita só com `confirmar=true`; sem ele,
registrar roda em dryRun e apagar só devolve o que seria apagado.

Ambiente:
- FINLYNQ_URL (obrigatório): ex.: http://192.168.68.10:3000/api/mcp (`/mcp` é redirect 308).
- FINLYNQ_TOKEN (obrigatório): API key `pf_*` (Settings → API Keys). Sem os dois o plugin não sobe.
"""
import asyncio
import json
import logging
import os
import re
from datetime import date

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP

log = logging.getLogger("dobi-mcp")

TIMEOUT = 20  # s; robô de voz não pode ficar mudo muito tempo
LIMITE_RESPOSTA = 2000  # caracteres de JSON devolvidos ao LLM
VALOR_MAXIMO = 1_000_000

TIPOS = {"despesa": -1, "receita": 1}
DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class EntradaInvalida(ValueError):
    pass


def _texto(valor: str, campo: str, maximo: int) -> str:
    valor = " ".join(str(valor).split())
    if not valor:
        raise EntradaInvalida(f"{campo} vazio")
    if len(valor) > maximo:
        raise EntradaInvalida(f"{campo} passa de {maximo} caracteres")
    return valor


def _opcional(valor: str, campo: str, maximo: int) -> str:
    return _texto(valor, campo, maximo) if str(valor).strip() else ""


def _inteiro(valor: int, campo: str, minimo: int, maximo: int) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
        raise EntradaInvalida(f"{campo} deve ser inteiro de {minimo} a {maximo}")
    return valor


def _valor(valor: float, campo: str, negativo: bool = False) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor != valor:
        raise EntradaInvalida(f"{campo} deve ser número")
    if not (negativo or valor > 0) or not 0 < abs(valor) <= VALOR_MAXIMO:
        faixa = "diferente de zero" if negativo else "positivo"
        raise EntradaInvalida(f"{campo} deve ser {faixa} e até {VALOR_MAXIMO}")
    return round(float(valor), 2)


def _escolha(valor: str, campo: str, opcoes) -> str:
    valor = str(valor).strip().lower()
    if valor not in opcoes:
        raise EntradaInvalida(f"{campo} deve ser um de: {', '.join(sorted(opcoes))}")
    return valor


def _data(valor: str) -> str:
    valor = str(valor).strip()
    if not valor:
        return ""
    try:
        if not DATA.match(valor):
            raise ValueError
        date.fromisoformat(valor)
    except ValueError:
        raise EntradaInvalida("data deve ser AAAA-MM-DD") from None
    return valor


def _sem_vazios(args: dict) -> dict:
    return {k: v for k, v in args.items() if v not in ("", None)}


def _enxugar(dados: dict) -> dict:
    """Corta itens da maior lista até o JSON caber em LIMITE_RESPOSTA."""
    if len(json.dumps(dados, ensure_ascii=False, default=str)) <= LIMITE_RESPOSTA:
        return dados
    listas = [k for k, v in dados.items() if isinstance(v, list)]
    if not listas:
        return {"erro": "resposta grande demais"}
    chave = max(listas, key=lambda k: len(dados[k]))
    dados = {**dados, chave: list(dados[chave]), "truncado": True}
    while dados[chave] and len(json.dumps(dados, ensure_ascii=False, default=str)) > LIMITE_RESPOSTA:
        dados[chave].pop()
    return dados


def _quantia(v):
    """Finlynq marca valores como {amount, currency, ...}; voz só precisa do número."""
    return v.get("amount") if isinstance(v, dict) else v


def _saldos(dados: dict) -> dict:
    contas = [{"id": c.get("id"), "nome": c.get("alias") or c.get("name"),
               "saldo": c.get("balance"), "moeda": c.get("currency")}
              for c in dados.get("accounts", []) if isinstance(c, dict)]
    return _sem_vazios({"contas": contas, "total": _quantia(dados.get("totalReporting")),
                        "moeda_total": dados.get("reportingCurrency"), "nota": dados.get("note")})


def _transacoes(dados: dict) -> dict:
    itens = [_sem_vazios({"id": t.get("id"), "data": t.get("date"), "favorecido": t.get("payee"),
                          "valor": t.get("amount"), "moeda": t.get("currency"),
                          "conta": t.get("account"), "categoria": t.get("category"),
                          "nota": t.get("note")})
             for t in dados.get("results", []) if isinstance(t, dict)]
    return {"transacoes": itens, "total": dados.get("count", len(itens))}


def _categorias(dados) -> dict:
    itens = [_sem_vazios({"id": c.get("id"), "nome": c.get("name"), "tipo": c.get("type"),
                          "grupo": c.get("group")})
             for c in (dados if isinstance(dados, list) else []) if isinstance(c, dict)]
    return {"categorias": itens}


async def _chamar(url: str, token: str, tool: str, args: dict):
    """Uma chamada = uma sessão. Devolve o `data` do envelope do Finlynq ou {"erro": ...}."""
    headers = {"Authorization": f"Bearer {token}"}
    async with asyncio.timeout(TIMEOUT):
        async with streamablehttp_client(url, headers=headers, timeout=TIMEOUT) as (leitura, escrita, _):
            async with ClientSession(leitura, escrita) as sessao:
                await sessao.initialize()
                r = await sessao.call_tool(tool, args)
    texto = " ".join(c.text for c in r.content if getattr(c, "type", "") == "text").strip()
    # Finlynq sinaliza erro de negócio com texto "Error: ...", sem isError
    if r.isError or texto.startswith("Error:"):
        return {"erro": texto.removeprefix("Error:").strip()[:300] or "erro no Finlynq"}
    try:
        dados = json.loads(texto)
    except ValueError:
        return {"resposta": texto[:LIMITE_RESPOSTA]}
    if isinstance(dados, dict) and dados.get("success") is True and "data" in dados:
        return dados["data"]
    return dados


def register(mcp: FastMCP) -> None:
    url = os.environ.get("FINLYNQ_URL", "").strip()
    token = os.environ.get("FINLYNQ_TOKEN", "").strip()
    if not url:
        raise RuntimeError("FINLYNQ_URL ausente")
    if not token:
        raise RuntimeError("FINLYNQ_TOKEN ausente")

    async def chamar(tool: str, montar, formatar=None) -> dict:
        try:
            args = montar()
        except EntradaInvalida as e:
            return {"erro": str(e)}
        try:
            dados = await _chamar(url, token, tool, args)
        except Exception as e:  # noqa: BLE001
            log.warning("finlynq %s falhou: %s", tool, type(e).__name__)
            return {"erro": f"Finlynq indisponível ({type(e).__name__})"}
        if isinstance(dados, dict) and "erro" in dados:
            return dados
        if formatar:
            dados = formatar(dados)
        return _enxugar(dados if isinstance(dados, dict) else {"resposta": dados})

    @mcp.tool()
    async def finlynq_saldos() -> dict:
        """Saldo de cada conta no Finlynq (finanças pessoais) e o total. Use quando
        perguntarem quanto tem numa conta ou em todas. Não invente números."""
        return await chamar("get_account_balances", dict, _saldos)

    @mcp.tool()
    async def finlynq_patrimonio() -> dict:
        """Patrimônio líquido no Finlynq: ativos, dívidas e total. Use quando
        perguntarem 'quanto eu tenho no total' ou 'meu patrimônio'."""
        return await chamar("get_net_worth", dict)

    @mcp.tool()
    async def finlynq_categorias() -> dict:
        """Categorias de transação do Finlynq (nome, tipo, grupo)."""
        return await chamar("get_categories", dict, _categorias)

    @mcp.tool()
    async def finlynq_buscar_transacoes(favorecido: str = "", categoria: str = "",
                                        data_inicio: str = "", data_fim: str = "",
                                        limite: int = 5) -> dict:
        """Busca transações no Finlynq ('quanto gastei no mercado esse mês?').
        favorecido: parte do nome (ex.: 'padaria'). categoria: nome exato.
        data_inicio/data_fim: AAAA-MM-DD. limite: 1 a 20. Valor negativo = despesa."""
        return await chamar("search_transactions", lambda: _sem_vazios({
            "payee": _opcional(favorecido, "favorecido", 100),
            "category": _opcional(categoria, "categoria", 60),
            "start_date": _data(data_inicio), "end_date": _data(data_fim),
            "limit": _inteiro(limite, "limite", 1, 20)}), _transacoes)

    @mcp.tool()
    async def finlynq_registrar_transacao(valor: float, favorecido: str, conta: str,
                                          tipo: str = "despesa", categoria: str = "",
                                          data: str = "", confirmar: bool = False) -> dict:
        """Registra uma transação no Finlynq. valor: sempre positivo; tipo: despesa | receita.
        conta: nome da conta (veja finlynq_saldos). categoria: opcional (vazio = automática).
        data: AAAA-MM-DD; vazio = hoje. Primeiro chame com confirmar=false (só simula),
        leia para o usuário valor, favorecido, conta e data, e só com o 'sim' dele
        chame de novo com confirmar=true."""
        def montar() -> dict:
            sinal = TIPOS[_escolha(tipo, "tipo", TIPOS)]
            return _sem_vazios({
                "op": "record", "amount": sinal * _valor(valor, "valor"),
                "payee": _texto(favorecido, "favorecido", 100),
                "account": _texto(conta, "conta", 60),
                "category": _opcional(categoria, "categoria", 60),
                "date": _data(data), "dryRun": not confirmar})
        r = await chamar("manage_transactions", montar)
        if not confirmar and "erro" not in r:
            r = {**r, "simulacao": True, "aviso": "nada gravado: confirme com o usuário"}
        return r

    @mcp.tool()
    async def finlynq_apagar_transacao(transacao_id: int, favorecido: str, valor: float,
                                       confirmar: bool = False) -> dict:
        """Apaga uma transação do Finlynq. Ache antes com finlynq_buscar_transacoes e
        passe id, favorecido e valor exatamente como vieram (valor com sinal); se não
        baterem, o Finlynq recusa. Primeiro chame com confirmar=false, leia para o
        usuário o que será apagado e só com o 'sim' dele chame com confirmar=true."""
        def montar() -> dict:
            return {"op": "delete", "id": _inteiro(transacao_id, "transacao_id", 1, 2**31 - 1),
                    "expected": {"payee": _texto(favorecido, "favorecido", 100),
                                 "amount": _valor(valor, "valor", negativo=True)}}
        if not confirmar:
            try:
                args = montar()
            except EntradaInvalida as e:
                return {"erro": str(e)}
            return {"simulacao": True, "apagaria": {"id": args["id"], **args["expected"]},
                    "aviso": "nada apagado: confirme com o usuário"}
        return await chamar("manage_transactions", montar)
