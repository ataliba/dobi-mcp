import platform
import time

import psutil
from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def status_servidor() -> dict:
        """Retorna uso de CPU, memória, disco e uptime do servidor onde este MCP roda.
        Use quando o usuário perguntar como está o servidor ou o homelab."""
        mem = psutil.virtual_memory()
        disco = psutil.disk_usage("/")
        uptime_h = (time.time() - psutil.boot_time()) / 3600
        return {
            "host": platform.node(),
            "cpu_pct": psutil.cpu_percent(interval=0.5),
            "mem_pct": mem.percent,
            "disco_pct": disco.percent,
            "uptime_horas": round(uptime_h, 1),
        }
