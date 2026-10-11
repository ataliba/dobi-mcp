"""Exemplo de tool personalizada. Habilite com ENABLED_TOOLS=...,eco"""
from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def eco(texto: str) -> dict:
        """Repete o texto recebido. Use só para testar se as tools personalizadas carregam."""
        return {"eco": texto[:100]}
