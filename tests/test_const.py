"""Sanidade do scaffold."""

import json
from pathlib import Path

import yaml

from custom_components.redes_moveis_fixas.const import DOMAIN, PLATFORMS


def test_domain():
    assert DOMAIN == "redes_moveis_fixas"
    assert "sensor" in PLATFORMS


def test_manifest_valido():
    manifest = json.loads(
        Path("custom_components/redes_moveis_fixas/manifest.json").read_text()
    )
    assert manifest["domain"] == DOMAIN
    assert manifest["dependencies"] == ["webhook"]
    assert manifest["integration_type"] == "hub"


def _chaves(d, prefixo=""):
    """Estrutura de chaves em ordem estável, ignorando os VALORES (que mudam
    por idioma) — só a forma (quais chaves, em qual aninhamento) importa.
    """
    chaves = set()
    for k, v in d.items():
        caminho = f"{prefixo}.{k}" if prefixo else k
        chaves.add(caminho)
        if isinstance(v, dict):
            chaves |= _chaves(v, caminho)
    return chaves


def test_services_com_nome_e_descricao_na_ui():
    """Finding 5: sem name/description, a UI renderia
    `redes_moveis_fixas.consultar_cobertura` cru com campos sem rótulo.

    strings.json (fonte, PT-BR) e as duas translations precisam ficar
    estruturalmente idênticas (mesma árvore de chaves) — só o texto muda.
    """
    base = Path("custom_components/redes_moveis_fixas")
    services_yaml = yaml.safe_load((base / "services.yaml").read_text())
    for nome, service in services_yaml.items():
        assert service.get("name"), f"{nome} sem name"
        assert service.get("description"), f"{nome} sem description"
        for campo, spec in service.get("fields", {}).items():
            assert spec.get("name"), f"{nome}.{campo} sem name"
            assert spec.get("description"), f"{nome}.{campo} sem description"

    arquivos = {
        "strings": json.loads((base / "strings.json").read_text()),
        "pt-BR": json.loads((base / "translations" / "pt-BR.json").read_text()),
        "en": json.loads((base / "translations" / "en.json").read_text()),
    }
    for nome, conteudo in arquivos.items():
        assert "services" in conteudo, f"{nome}.json sem bloco 'services'"

    referencia = _chaves(arquivos["strings"]["services"])
    for nome in ("pt-BR", "en"):
        assert _chaves(arquivos[nome]["services"]) == referencia, (
            f"services em {nome}.json difere estruturalmente de strings.json"
        )
