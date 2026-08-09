"""Sanidade do scaffold."""

import json
from pathlib import Path

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
