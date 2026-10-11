from datetime import datetime

from mcp.server.fastmcp import FastMCP

from tools._comum import DIAS_SEMANA, TZ


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def data_hora() -> dict:
        """Retorna a data e a hora atuais no horário de Brasília.
        Use quando o usuário perguntar que horas são ou que dia é hoje."""
        agora = datetime.now(TZ)
        return {"data": agora.strftime("%d/%m/%Y"), "hora": agora.strftime("%H:%M"),
                "dia_semana": DIAS_SEMANA[agora.weekday()]}
