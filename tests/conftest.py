"""Fixtures compartilhadas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    """Carrega fixture JSON (re-lê a cada chamada; pode mutar)."""
    return json.loads((FIXTURE_DIR / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Habilita custom integrations em todos os testes."""
    yield
