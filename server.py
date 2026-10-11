"""Servidor MCP mínimo para agentes XiaoZhi (ex.: robô Dobi).

Tools oficiais ficam em tools/ e as personalizadas em CUSTOM_TOOLS_DIR (padrão
custom_tools/); um módulo por tema, cada um com `register(mcp)`, ativados
explicitamente por ENABLED_TOOLS ou config.yaml. Roda via stdio; quem conecta na
nuvem é o pipe.py.
"""
import logging
import sys

from mcp.server.fastmcp import FastMCP

import tools

# stdout é o canal do protocolo MCP: log SEMPRE em stderr
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s [server] %(message)s")

mcp = FastMCP("dobi-mcp")
tools.carregar(mcp, custom=tools.diretorio_custom())

if __name__ == "__main__":
    mcp.run(transport="stdio")
