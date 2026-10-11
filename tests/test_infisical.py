"""USE_INFISICAL liga/desliga a reexecução do pipe.py sob `infisical run`."""
import sys

import pytest

from pipe import SENTINELA, comando_infisical

ARGV = ["pipe.py", "server.py"]


@pytest.mark.parametrize("valor", [None, "", "0", "false", "nao", "off"])
def test_desligado(valor):
    env = {} if valor is None else {"USE_INFISICAL": valor}
    assert comando_infisical(env, ARGV) is None


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", " yes ", "on", "sim"])
def test_ligado_minimo(valor):
    assert comando_infisical({"USE_INFISICAL": valor}, ARGV) == [
        "infisical", "run", "--silent", "--", sys.executable, "pipe.py", "server.py"]


def test_flags_opcionais():
    env = {"USE_INFISICAL": "1", "INFISICAL_ENV": "prod",
           "INFISICAL_PROJECT_ID": "abc", "INFISICAL_PATH": "/dobi"}
    cmd = comando_infisical(env, ARGV)
    assert cmd[:6] == ["infisical", "run", "--silent",
                       "--env=prod", "--projectId=abc", "--path=/dobi"]
    assert cmd[6:] == ["--", sys.executable, "pipe.py", "server.py"]


def test_sentinela_evita_loop():
    assert comando_infisical({"USE_INFISICAL": "1", SENTINELA: "1"}, ARGV) is None
