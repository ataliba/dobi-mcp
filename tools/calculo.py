import logging

from mcp.server.fastmcp import FastMCP
from simpleeval import simple_eval

log = logging.getLogger("dobi-mcp")


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def calcular(expressao: str) -> dict:
        """Calcula uma expressão matemática simples, como '2**10 / 3' ou '15 * 7'.
        Use sempre que o usuário pedir uma conta. Não executa código arbitrário."""
        if len(expressao) > 200:
            return {"ok": False, "erro": "expressão longa demais"}
        try:
            resultado = simple_eval(expressao)
            log.info("calcular %r = %r", expressao, resultado)
            return {"ok": True, "resultado": resultado}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)[:200]}
