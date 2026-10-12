"""USE_INFISICAL: reexecução sob `infisical run` e login Universal Auth."""
import os
import subprocess
import sys

import pytest

import pipe
from pipe import (SENTINELA, UA_ID, UA_SECRET, ErroInfisical, comando_infisical, comando_login,
                  token_de_sessao, usa_universal_auth)

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


def test_domain_vem_de_infisical_api_url():
    cmd = comando_infisical({"USE_INFISICAL": "1", "INFISICAL_API_URL": "https://inf.lan"}, ARGV)
    assert "--domain=https://inf.lan" in cmd


@pytest.mark.parametrize("env,esperado", [
    ({UA_ID: "id", UA_SECRET: "s"}, True),
    ({UA_ID: "id"}, False),
    ({UA_ID: " ", UA_SECRET: "s"}, False),
    ({}, False),
])
def test_usa_universal_auth(env, esperado):
    assert usa_universal_auth(env) is esperado


def test_login_nao_passa_segredo_por_argumento():
    env = {UA_ID: "meu-id", UA_SECRET: "segredo-xyz", "INFISICAL_API_URL": "https://inf.lan"}
    cmd = comando_login(env)
    assert cmd == ["infisical", "login", "--method=universal-auth", "--silent", "--plain",
                   "--domain=https://inf.lan"]
    assert not any("segredo-xyz" in a or "meu-id" in a for a in cmd)


def _fake(stdout="", stderr="", rc=0, erro=None):
    chamadas = []

    def executar(cmd, **kw):
        chamadas.append((cmd, kw))
        if erro:
            raise erro
        return subprocess.CompletedProcess(cmd, rc, stdout, stderr)

    executar.chamadas = chamadas
    return executar


def test_token_de_sessao_ok():
    env = {UA_ID: "id", UA_SECRET: "s"}
    fake = _fake(stdout="aviso qualquer\neyJtoken\n")
    assert token_de_sessao(env, fake) == "eyJtoken"
    assert fake.chamadas[0][1]["env"] is env


def test_token_de_sessao_falha_mascara_segredo():
    env = {UA_ID: "id", UA_SECRET: "segredo-xyz"}
    fake = _fake(stderr="invalid client secret segredo-xyz", rc=1)
    with pytest.raises(ErroInfisical, match=r"código 1.*\*\*\*") as e:
        token_de_sessao(env, fake)
    assert "segredo-xyz" not in str(e.value)


@pytest.mark.parametrize("fake", [_fake(stdout="  \n"), _fake(erro=FileNotFoundError()),
                                  _fake(erro=subprocess.TimeoutExpired("infisical", 60))])
def test_token_de_sessao_vazio_ou_erro(fake):
    with pytest.raises(ErroInfisical):
        token_de_sessao({UA_ID: "id", UA_SECRET: "s"}, fake)


def test_talvez_infisical_troca_credencial_por_sessao(monkeypatch):
    monkeypatch.setattr(os, "environ", {"USE_INFISICAL": "1", "INFISICAL_ENV": "prod",
                                        "INFISICAL_TOKEN": "st.velho",
                                        UA_ID: "id", UA_SECRET: "s"})
    monkeypatch.setattr(sys, "argv", ARGV)
    monkeypatch.setattr(pipe.shutil, "which", lambda _: "/usr/bin/infisical")
    monkeypatch.setattr(pipe, "token_de_sessao", lambda env: "eyJsessao")
    capturado = {}

    def execvpe(arq, cmd, env):
        capturado.update(arq=arq, cmd=cmd, env=env)

    monkeypatch.setattr(os, "execvpe", execvpe)
    pipe.talvez_infisical()
    env = capturado["env"]
    assert env["INFISICAL_TOKEN"] == "eyJsessao"  # sessão nova vence token antigo
    assert UA_SECRET not in env
    assert env[SENTINELA] == "1"
    assert capturado["cmd"][:4] == ["infisical", "run", "--silent", "--env=prod"]
