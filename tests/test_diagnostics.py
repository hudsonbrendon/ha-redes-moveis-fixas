"""Testes de diagnostics."""

from custom_components.redes_moveis_fixas.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .test_sensor import _setup


async def test_diagnostics_redige_segredos(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    diag = await async_get_config_entry_diagnostics(hass, entry_completa)
    assert diag["entry"]["data"]["token"] == "**REDACTED**"
    for sub in diag["subentries"]:
        assert sub["data"].get("monitor_secret") in (None, "**REDACTED**")
    assert diag["health"]["status"] == "ok"
