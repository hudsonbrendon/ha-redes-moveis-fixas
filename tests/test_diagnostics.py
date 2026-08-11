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
    assert diag["entry"]["data"]["webhook_id"] == "**REDACTED**"
    for sub in diag["subentries"]:
        assert sub["data"].get("monitor_secret") in (None, "**REDACTED**")
    assert diag["health"]["status"] == "ok"


async def test_diagnostics_filtra_secret_dos_monitores(
    hass, entry_completa, mock_client
):
    """rt.monitores.data vem direto da API (não passa por async_redact_data);
    a filtragem de "secret" é manual em diagnostics.py — prova que ela funciona.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    mock_client.async_listar_monitores.return_value = [
        {"id": "mon1", "ativo": True, "secret": "whsec_super_secreto"}
    ]
    await entry_completa.runtime_data.monitores.async_refresh()

    diag = await async_get_config_entry_diagnostics(hass, entry_completa)
    assert "secret" not in diag["monitores"]["mon1"]
    assert diag["monitores"]["mon1"]["ativo"] is True


async def test_diagnostics_nao_vaza_url_do_webhook_nos_monitores(
    hass, entry_completa, mock_client
):
    """rt.monitores.data traz `url` = URL pública completa do nosso webhook
    (hostname externo do usuário + o próprio webhook_id). Sem filtrar esse
    campo, diagnostics republica em claro o que A_REDIGIR acabou de redigir
    em entry.data["webhook_id"] — achado Blocking 2 do relatório final.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    mock_client.async_listar_monitores.return_value = [
        {
            "id": "mon1",
            "ativo": True,
            "secret": "whsec_super_secreto",
            "url": "https://ha.example.com/api/webhook/wh_fixo",
        }
    ]
    await entry_completa.runtime_data.monitores.async_refresh()

    diag = await async_get_config_entry_diagnostics(hass, entry_completa)
    mon = diag["monitores"]["mon1"]
    assert "url" not in mon
    assert "ha.example.com" not in str(diag["monitores"])
    assert "wh_fixo" not in str(diag["monitores"])
    assert mon["ativo"] is True
