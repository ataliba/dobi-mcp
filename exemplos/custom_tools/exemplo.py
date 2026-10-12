"""Exemplo de tool personalizada do dobi-mcp.

Como usar:
    cp exemplos/custom_tools/exemplo.py custom_tools/
    # reinicie: tudo em custom_tools/ sobe sozinho (não precisa de ENABLED_TOOLS)

Regras de uma tool personalizada:
- Um arquivo .py em custom_tools/, nome em minúsculas (a-z, 0-9, _). Arquivo começando
  com `_` é helper: pode ser importado (`from custom_tools._util import ...`), mas não vira tool.
- Exporta `register(mcp)` e declara as tools com `@mcp.tool()` DENTRO dela.
- Não pode ter o mesmo nome de arquivo de uma tool oficial (tools/) nem o mesmo nome de
  tool: no primeiro caso é ignorada, no segundo o boot falha com ColisaoDeTools.
- Nome da função + docstring são o que o LLM lê para decidir quando chamar: seja claro.
- Entrada vem de VOZ = não confiável: valide tudo. Retorno pequeno (< ~1 KB), sem segredos.
- Segredo vem do ambiente (.env ou Infisical), nunca escrito no arquivo.
- Log só em stderr (logging); stdout é o canal do protocolo MCP: nada de print().
- Nada de eval/exec.
"""
import logging
import os

from mcp.server.fastmcp import FastMCP

log = logging.getLogger("dobi-mcp")

LIMITE = 100  # caracteres devolvidos pelo eco


def register(mcp: FastMCP) -> None:
    # Configuração lida uma vez no boot. Se faltar algo obrigatório, levante uma exceção:
    # o loader loga o motivo, ignora só este plugin e o resto sobe normal. Ex.:
    #   token = os.environ.get("MEU_TOKEN") or ""
    #   if not token: raise RuntimeError("MEU_TOKEN ausente")
    prefixo = os.environ.get("ECO_PREFIXO", "").strip()[:20]

    @mcp.tool()
    def eco(texto: str) -> dict:
        """Repete o texto recebido. Use quando o usuário pedir para testar o eco
        ou 'repete o que eu disse'."""
        texto = " ".join(str(texto).split())  # normaliza espaços vindos da transcrição
        if not texto:
            return {"erro": "texto vazio"}  # erro como dado: o robô pode perguntar de novo
        log.info("eco chamado (%d caracteres)", len(texto))  # vai para stderr
        return {"eco": f"{prefixo}{texto}"[:LIMITE]}

    # Uma tool pode ser async (útil para chamar APIs com httpx) e ter várias por arquivo:
    #
    # @mcp.tool()
    # async def outra(cidade: str) -> dict:
    #     """..."""
    #     async with httpx.AsyncClient(timeout=10) as c:
    #         r = await c.get("https://...", params={"q": cidade})
    #     return {"resultado": r.json()["campo"]}
