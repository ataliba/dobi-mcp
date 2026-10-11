"""Tools do dobi-mcp. Cada módulo aqui expõe `register(mcp)`.

Duas origens:
- oficiais: este pacote (`tools/`), embutidas na imagem;
- personalizadas: diretório `CUSTOM_TOOLS_DIR` (padrão `custom_tools/`, montado
  como volume), exposto como pacote `custom_tools` sem precisar de `__init__.py`.

Só são importados os módulos habilitados explicitamente em `ENABLED_TOOLS`
(env, separado por vírgula) ou, se ausente, em `config.yaml` (`enabled_tools`).
Mesmo nome nas duas origens → vale a oficial. Módulos começando com `_` são
internos (helpers) e nunca são carregados como plugin.
"""
import importlib
import logging
import os
import re
import sys
import types
from pathlib import Path

from mcp.server.fastmcp import FastMCP

log = logging.getLogger("dobi-mcp")

NOME_VALIDO = re.compile(r"^[a-z][a-z0-9_]*$")
RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PADRAO = RAIZ / "config.yaml"


class ColisaoDeTools(RuntimeError):
    """Duas tools com o mesmo nome: falha no boot em vez de sobrescrever em silêncio."""


def nomes_habilitados(env: dict | None = None, config: Path = CONFIG_PADRAO) -> list[str]:
    """Lista de plugins ativos: ENABLED_TOOLS (env) ou, se ausente/vazia, config.yaml."""
    env = os.environ if env is None else env
    bruto = env.get("ENABLED_TOOLS", "").strip()
    if not bruto and config.is_file():
        import yaml  # só quando o fallback é usado

        dados = yaml.safe_load(config.read_text()) or {}
        bruto = (dados.get("enabled_tools") or []) if isinstance(dados, dict) else []
    if isinstance(bruto, str):
        bruto = bruto.split(",")
    nomes = []
    for n in bruto:
        n = str(n).strip()
        if n and n not in nomes:
            nomes.append(n)
    return nomes


def diretorio_custom(env: dict | None = None) -> Path:
    """Diretório das tools personalizadas: CUSTOM_TOOLS_DIR ou <raiz>/custom_tools."""
    env = os.environ if env is None else env
    return Path(env.get("CUSTOM_TOOLS_DIR", "").strip() or RAIZ / "custom_tools")


def _expor_pacote(diretorio: Path, nome: str) -> str:
    """Registra `diretorio` como pacote `nome` (dispensa __init__.py no volume)."""
    for mod in [m for m in sys.modules if m == nome or m.startswith(nome + ".")]:
        del sys.modules[mod]
    pacote = types.ModuleType(nome, "Tools personalizadas (volume).")
    pacote.__path__ = [str(diretorio.resolve())]
    pacote.__package__ = nome
    sys.modules[nome] = pacote
    importlib.invalidate_caches()
    return nome


class _Registrador:
    """Proxy do FastMCP entregue ao `register()` de cada plugin.

    Acumula as tools declaradas e só as aplica no servidor real depois que o
    `register()` termina sem erro: plugin que quebra no meio não deixa tool pela metade.
    """

    def __init__(self, mcp: FastMCP):
        self._mcp = mcp
        self.pendentes: list[tuple[str, object, dict]] = []

    def tool(self, name: str | None = None, **kwargs):
        if callable(name):
            raise TypeError("use @mcp.tool() com parênteses")

        def decorador(fn):
            self.pendentes.append((name or fn.__name__, fn, {"name": name, **kwargs}))
            return fn

        return decorador

    def __getattr__(self, attr):  # resource(), prompt() etc. vão direto ao servidor
        return getattr(self._mcp, attr)


def carregar(mcp: FastMCP, nomes: list[str] | None = None, pacote: str = __name__,
             custom: Path | None = None, pacote_custom: str = "custom_tools") -> dict:
    """Importa só os plugins habilitados e chama `register(mcp)` de cada um.

    Procura cada nome primeiro nas oficiais (`pacote`) e depois em `custom`
    (diretório opcional; inexistente = sem personalizadas). Plugin quebrado é
    logado e ignorado; colisão de nomes de tool levanta ColisaoDeTools.
    Retorna {"ativas": {plugin: [tools]}, "ignoradas": {nome: motivo}};
    plugins personalizados aparecem como "custom/<nome>".
    """
    if nomes is None:
        nomes = nomes_habilitados()
    origens = [(pacote, Path(importlib.import_module(pacote).__path__[0]), "")]
    if custom is not None and custom.is_dir():
        origens.append((_expor_pacote(custom, pacote_custom), custom, "custom/"))
    elif custom is not None:
        log.info("sem tools personalizadas: %s não existe", custom)
    donos: dict[str, str] = {}  # nome da tool -> plugin que a registrou
    ativas: dict[str, list[str]] = {}
    ignoradas: dict[str, str] = {}

    def ignorar(nome: str, motivo: str) -> None:
        ignoradas[nome] = motivo
        log.warning("tool %s ignorada: %s", nome, motivo)

    for nome in nomes:
        if not NOME_VALIDO.match(nome):
            ignorar(repr(nome[:40]), "nome inválido")
            continue
        achadas = [o for o in origens if (o[1] / f"{nome}.py").is_file()]
        if not achadas:
            ignorar(nome, "arquivo ausente")
            continue
        pkg, _, prefixo = achadas[0]
        rotulo = prefixo + nome
        for _, _, outro in achadas[1:]:
            ignorar(outro + nome, "mesmo nome de uma tool oficial")
        try:
            modulo = importlib.import_module(f"{pkg}.{nome}")
        except Exception as e:  # noqa: BLE001
            ignorar(rotulo, f"erro de import: {type(e).__name__}: {str(e)[:120]}")
            continue
        register = getattr(modulo, "register", None)
        if not callable(register):
            ignorar(rotulo, "sem register(mcp)")
            continue
        reg = _Registrador(mcp)
        try:
            register(reg)
        except Exception as e:  # noqa: BLE001
            ignorar(rotulo, f"erro em register: {type(e).__name__}: {str(e)[:120]}")
            continue
        for tool, _, _ in reg.pendentes:
            if tool in donos:
                raise ColisaoDeTools(
                    f"tool {tool!r} registrada por {donos[tool]} e por {pkg}.{nome}")
            donos[tool] = f"{pkg}.{nome}"
        for _, fn, kwargs in reg.pendentes:
            mcp.tool(**kwargs)(fn)
        ativas[rotulo] = [t for t, _, _ in reg.pendentes]
        log.info("%s/%s.py carregado: %s", pkg, nome, ", ".join(ativas[rotulo]) or "-")

    for _, diretorio, prefixo in origens:
        for arq in sorted(diretorio.glob("*.py")):
            if not arq.stem.startswith("_") and arq.stem not in nomes:
                ignoradas[prefixo + arq.stem] = "não habilitada"

    log.info("tools ativas (%d): %s | ignoradas: %s", len(ativas), ", ".join(ativas) or "-",
             ", ".join(f"{n} ({m})" for n, m in ignoradas.items()) or "-")
    return {"ativas": ativas, "ignoradas": ignoradas}
