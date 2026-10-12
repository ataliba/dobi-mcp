"""Loader de tools/: ativação explícita, isolamento de falha, validação e colisão."""
import asyncio
import itertools
import re
import sys
import textwrap

import pytest
from mcp.server.fastmcp import FastMCP

import tools
from tools import ColisaoDeTools, carregar, nomes_habilitados

_seq = itertools.count()

PLUGIN_OK = """
def register(mcp):
    @mcp.tool()
    def {tool}() -> dict:
        "Tool de teste."
        return {{"ok": True}}
"""


@pytest.fixture
def pacote(tmp_path, monkeypatch):
    """Cria um pacote de plugins descartável (nome único evita cache de sys.modules)."""
    nome = f"plugins_teste_{next(_seq)}"
    raiz = tmp_path / nome
    raiz.mkdir()
    (raiz / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))

    def escrever(arquivo: str, codigo: str) -> None:
        (raiz / f"{arquivo}.py").write_text(textwrap.dedent(codigo))

    escrever.nome = nome
    yield escrever
    for mod in [m for m in sys.modules if m == nome or m.startswith(nome + ".")]:
        del sys.modules[mod]


def nomes_tools(mcp: FastMCP) -> set[str]:
    return {t.name for t in asyncio.run(mcp.list_tools())}


def test_carrega_so_as_listadas(pacote):
    pacote("a", PLUGIN_OK.format(tool="tool_a"))
    pacote("b", PLUGIN_OK.format(tool="tool_b"))
    pacote("c", "raise RuntimeError('não devia ser importado')")
    mcp = FastMCP("t")
    inv = carregar(mcp, ["a", "b"], pacote=pacote.nome)
    assert nomes_tools(mcp) == {"tool_a", "tool_b"}
    assert f"{pacote.nome}.c" not in sys.modules
    assert inv["ignoradas"] == {"c": "não habilitada"}


def test_ferramentas_reais_respeitam_lista():
    mcp = FastMCP("t")
    carregar(mcp, ["calculo", "tempo"])
    assert nomes_tools(mcp) == {"calcular", "data_hora"}


def test_erro_de_import_nao_derruba_os_outros(pacote, caplog):
    pacote("quebrado", "import modulo_que_nao_existe_xyz\n")
    pacote("explode", "def register(mcp):\n    raise ValueError('boom')\n")
    pacote("bom", PLUGIN_OK.format(tool="tool_boa"))
    mcp = FastMCP("t")
    inv = carregar(mcp, ["quebrado", "explode", "bom"], pacote=pacote.nome)
    assert nomes_tools(mcp) == {"tool_boa"}
    assert inv["ignoradas"]["quebrado"].startswith("erro de import: ModuleNotFoundError")
    assert inv["ignoradas"]["explode"] == "erro em register: ValueError: boom"
    assert "modulo_que_nao_existe_xyz" in caplog.text


def test_register_que_falha_no_meio_nao_deixa_tool_parcial(pacote):
    pacote("meio", """
        def register(mcp):
            @mcp.tool()
            def parcial() -> dict:
                "x"
                return {}
            raise RuntimeError("depois da primeira tool")
    """)
    mcp = FastMCP("t")
    carregar(mcp, ["meio"], pacote=pacote.nome)
    assert nomes_tools(mcp) == set()


@pytest.mark.parametrize("nome", ["../algo", "Calculo", "_comum", "1abc", "a-b", "a/b", "a.b", "a b"])
def test_nome_invalido_rejeitado(nome, pacote):
    pacote("valido", PLUGIN_OK.format(tool="tool_valida"))
    mcp = FastMCP("t")
    inv = carregar(mcp, [nome, "valido"], pacote=pacote.nome)
    assert inv["ignoradas"][repr(nome)] == "nome inválido"
    assert nomes_tools(mcp) == {"tool_valida"}


def test_arquivo_ausente_vira_warning(pacote, caplog):
    mcp = FastMCP("t")
    inv = carregar(mcp, ["fantasma"], pacote=pacote.nome)
    assert inv["ignoradas"] == {"fantasma": "arquivo ausente"}
    assert "fantasma" in caplog.text


def test_colisao_de_nomes_levanta(pacote):
    pacote("um", PLUGIN_OK.format(tool="repetida"))
    pacote("dois", PLUGIN_OK.format(tool="repetida"))
    with pytest.raises(ColisaoDeTools, match=r"'repetida'.*\.um.*\.dois"):
        carregar(FastMCP("t"), ["um", "dois"], pacote=pacote.nome)


def test_inventario_em_uma_linha(pacote, caplog):
    caplog.set_level("INFO", logger="dobi-mcp")
    pacote("a", PLUGIN_OK.format(tool="tool_a"))
    pacote("sobra", PLUGIN_OK.format(tool="tool_sobra"))
    carregar(FastMCP("t"), ["a", "../x", "fantasma"], pacote=pacote.nome)
    linhas = [r.getMessage() for r in caplog.records if r.getMessage().startswith("tools ativas")]
    assert linhas == ["tools ativas (1): a | ignoradas: '../x' (nome inválido), "
                      "fantasma (arquivo ausente), sobra (não habilitada)"]


def test_env_tem_precedencia_sobre_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("enabled_tools: [tempo, sistema]\n")
    assert nomes_habilitados({"ENABLED_TOOLS": " calculo , tempo,,calculo "}, cfg) == ["calculo", "tempo"]
    assert nomes_habilitados({}, cfg) == ["tempo", "sistema"]
    assert nomes_habilitados({"ENABLED_TOOLS": "  "}, cfg) == ["tempo", "sistema"]
    assert nomes_habilitados({}, tmp_path / "nao_existe.yaml") == []


def test_tools_nao_usam_eval_exec():
    proibido = re.compile(r"(?<![\w.])(eval|exec)\s*\(")
    arquivos = [*(tools.RAIZ / "tools").glob("*.py"), *(tools.RAIZ / "custom_tools").glob("*.py"),
                *(tools.RAIZ / "exemplos").rglob("*.py")]
    for arq in arquivos:
        assert not proibido.search(arq.read_text()), arq.name


@pytest.fixture
def custom(tmp_path):
    """Diretório de tools personalizadas (sem __init__.py, como num volume)."""
    raiz = tmp_path / "volume_custom"
    raiz.mkdir()
    nome = f"custom_teste_{next(_seq)}"

    def escrever(arquivo: str, codigo: str) -> None:
        (raiz / f"{arquivo}.py").write_text(textwrap.dedent(codigo))

    escrever.dir = raiz
    escrever.nome = nome
    yield escrever
    for mod in [m for m in sys.modules if m == nome or m.startswith(nome + ".")]:
        del sys.modules[mod]


def test_custom_carrega_so_por_estar_no_diretorio(pacote, custom):
    pacote("oficial", PLUGIN_OK.format(tool="tool_oficial"))
    pacote("desligada", PLUGIN_OK.format(tool="tool_desligada"))
    custom("minha", PLUGIN_OK.format(tool="tool_minha"))
    custom("outra", PLUGIN_OK.format(tool="tool_outra"))
    custom("_helper", "raise RuntimeError('helper não é plugin')\n")
    mcp = FastMCP("t")
    inv = carregar(mcp, ["oficial"], pacote=pacote.nome,
                   custom=custom.dir, pacote_custom=custom.nome)
    assert nomes_tools(mcp) == {"tool_oficial", "tool_minha", "tool_outra"}
    assert inv["ativas"] == {"oficial": ["tool_oficial"], "custom/minha": ["tool_minha"],
                             "custom/outra": ["tool_outra"]}
    assert inv["ignoradas"] == {"desligada": "não habilitada"}


def test_custom_listada_em_enabled_nao_duplica_nem_avisa(pacote, custom):
    custom("minha", PLUGIN_OK.format(tool="tool_minha"))
    mcp = FastMCP("t")
    inv = carregar(mcp, ["minha"], pacote=pacote.nome,
                   custom=custom.dir, pacote_custom=custom.nome)
    assert nomes_tools(mcp) == {"tool_minha"}
    assert inv["ignoradas"] == {}


def test_custom_com_nome_invalido_ignorada(pacote, custom):
    custom("Maiuscula", PLUGIN_OK.format(tool="tool_x"))
    custom("com-hifen", PLUGIN_OK.format(tool="tool_y"))
    mcp = FastMCP("t")
    inv = carregar(mcp, [], pacote=pacote.nome, custom=custom.dir, pacote_custom=custom.nome)
    assert nomes_tools(mcp) == set()
    assert inv["ignoradas"] == {"custom/'Maiuscula'": "nome inválido",
                                "custom/'com-hifen'": "nome inválido"}


def test_custom_importa_helper_proprio_e_oficial(pacote, custom):
    custom("_util", "PREFIXO = 'x'\n")
    custom("usa", """
        from {pkg}._util import PREFIXO
        from tools._comum import TZ

        def register(mcp):
            @mcp.tool()
            def usa_helper() -> dict:
                "x"
                return {{"p": PREFIXO, "tz": str(TZ)}}
    """.replace("{pkg}", custom.nome))
    mcp = FastMCP("t")
    carregar(mcp, [], pacote=pacote.nome, custom=custom.dir, pacote_custom=custom.nome)
    assert nomes_tools(mcp) == {"usa_helper"}


@pytest.mark.parametrize("habilitada", [True, False])
def test_custom_nunca_substitui_oficial(pacote, custom, habilitada):
    pacote("dup", PLUGIN_OK.format(tool="da_oficial"))
    custom("dup", PLUGIN_OK.format(tool="da_custom"))
    mcp = FastMCP("t")
    inv = carregar(mcp, ["dup"] if habilitada else [], pacote=pacote.nome,
                   custom=custom.dir, pacote_custom=custom.nome)
    assert nomes_tools(mcp) == ({"da_oficial"} if habilitada else set())
    assert inv["ignoradas"]["custom/dup"] == "mesmo nome de uma tool oficial"
    assert f"{custom.nome}.dup" not in sys.modules


def test_colisao_entre_oficial_e_custom_levanta(pacote, custom):
    pacote("um", PLUGIN_OK.format(tool="repetida"))
    custom("dois", PLUGIN_OK.format(tool="repetida"))
    with pytest.raises(ColisaoDeTools, match=r"'repetida'.*\.um.*custom_teste_\d+\.dois"):
        carregar(FastMCP("t"), ["um"], pacote=pacote.nome,
                 custom=custom.dir, pacote_custom=custom.nome)


def test_custom_quebrada_nao_derruba_oficiais(pacote, custom):
    pacote("bom", PLUGIN_OK.format(tool="tool_boa"))
    custom("ruim", "raise RuntimeError('quebrei')\n")
    mcp = FastMCP("t")
    inv = carregar(mcp, ["bom"], pacote=pacote.nome,
                   custom=custom.dir, pacote_custom=custom.nome)
    assert nomes_tools(mcp) == {"tool_boa"}
    assert inv["ignoradas"]["custom/ruim"] == "erro de import: RuntimeError: quebrei"


def test_dir_custom_inexistente_e_ok(pacote, tmp_path):
    pacote("a", PLUGIN_OK.format(tool="tool_a"))
    mcp = FastMCP("t")
    inv = carregar(mcp, ["a", "fantasma"], pacote=pacote.nome, custom=tmp_path / "nao_existe")
    assert nomes_tools(mcp) == {"tool_a"}
    assert inv["ignoradas"] == {"fantasma": "arquivo ausente"}


def test_diretorio_custom_env(tmp_path):
    assert tools.diretorio_custom({"CUSTOM_TOOLS_DIR": str(tmp_path)}) == tmp_path
    assert tools.diretorio_custom({}) == tools.RAIZ / "custom_tools"


def test_helper_com_underline_nunca_sobe(custom):
    custom("_exemplo", PLUGIN_OK.format(tool="nao_devia"))
    mcp = FastMCP("t")
    inv = carregar(mcp, ["tempo"], custom=custom.dir, pacote_custom=custom.nome)
    assert nomes_tools(mcp) == {"data_hora"}
    assert inv["ignoradas"] == {"calculo": "não habilitada", "feriados": "não habilitada",
                                "sistema": "não habilitada"}


def test_exemplo_versionado_funciona(custom):
    """exemplos/custom_tools/exemplo.py copiado para o volume sobe e responde."""
    custom("exemplo", (tools.RAIZ / "exemplos" / "custom_tools" / "exemplo.py").read_text())
    mcp = FastMCP("t")
    inv = carregar(mcp, [], pacote="tools", custom=custom.dir, pacote_custom=custom.nome)
    assert inv["ativas"] == {"custom/exemplo": ["eco"]}
    r = asyncio.run(mcp.call_tool("eco", {"texto": "  olá   dobi "}))
    conteudo = r[0] if isinstance(r, tuple) else r
    assert '"eco": "olá dobi"' in conteudo[0].text
