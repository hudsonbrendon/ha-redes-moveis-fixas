"""Testes de setup/unload da entry."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.helpers.network import NoURLAvailableError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.api import RMFAuthError, RMFError
from custom_components.redes_moveis_fixas.const import DOMAIN


async def test_setup_e_unload(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    client = mock_client
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(entry_completa.entry_id)
        await hass.async_block_till_done()

    assert entry_completa.state is ConfigEntryState.LOADED
    rt = entry_completa.runtime_data
    assert len(rt.cobertura) == 1
    assert len(rt.erbs) == 1
    assert len(rt.municipio) == 1
    # coordenadas da zona chegaram no coordinator
    coord = list(rt.cobertura.values())[0]
    assert coord.lat == -5.8
    assert coord.lon == -35.2

    # monitores provisionados: secret gravado na subentry
    subs = {s.subentry_type: s for s in entry_completa.subentries.values()}
    assert subs["monitor_ios"].data["monitor_secret"] == "whsec_test_1d90aa"
    assert subs["monitor_ios"].data["monitor_id"] == "3ab7f001"
    assert subs["municipio"].data["monitor_id"] == "9f1c0001"
    assert subs["municipio"].data["monitor_secret"] == "whsec_cidade_aa"
    client.async_criar_monitor_ios.assert_awaited_once()
    client.async_criar_monitor_cidade.assert_awaited_once()

    assert await hass.config_entries.async_unload(entry_completa.entry_id)
    assert entry_completa.state is ConfigEntryState.NOT_LOADED


async def test_setup_nao_recria_monitor_existente(hass, mock_client):
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": "wh_fixo"},
        unique_id="uid2",
        subentries_data=[
            ConfigSubentryData(
                data={
                    "paises": ["BR"],
                    "operadoras": [],
                    "incluir_beta": False,
                    "monitor_id": "3ab7f001",
                    "monitor_secret": "whsec_ja_tem",
                },
                subentry_type="monitor_ios",
                title="Monitor iOS",
                unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    client = mock_client
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    client.async_criar_monitor_ios.assert_not_awaited()


async def test_webhook_registrado_e_publico(hass, entry_completa, mock_client):
    """O webhook precisa aceitar POST vindo da internet (local_only=False)."""
    client = mock_client
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_register"
        ) as registrar,
    ):
        assert await hass.config_entries.async_setup(entry_completa.entry_id)
        await hass.async_block_till_done()

    kwargs = registrar.call_args.kwargs
    assert kwargs["local_only"] is False
    assert list(kwargs["allowed_methods"]) == ["POST"]


async def test_modo_pessoa_segue_deslocamento(hass, freezer, mock_client):
    """Só refaz a consulta se andou >500 m; movimento curto é ignorado."""
    from custom_components.redes_moveis_fixas.const import SUBENTRY_LOCAL

    hass.states.async_set(
        "person.hudson", "home", {"latitude": -5.8, "longitude": -35.2}
    )
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": "wh_fixo"},
        unique_id="uid3",
        subentries_data=[
            ConfigSubentryData(
                data={
                    "modo": "pessoa",
                    "entity_id": "person.hudson",
                    "intervalo_cobertura": 30,
                    "intervalo_erbs": 6,
                    "max_geo": 25,
                },
                subentry_type=SUBENTRY_LOCAL,
                title="Hudson",
                unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    client = mock_client
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()

    sid = next(iter(e.runtime_data.cobertura))
    coord = e.runtime_data.cobertura[sid]
    erbs = e.runtime_data.erbs[sid]

    # ~20 m: abaixo do mínimo, não atualiza
    hass.states.async_set(
        "person.hudson", "home", {"latitude": -5.8002, "longitude": -35.2}
    )
    await hass.async_block_till_done()
    assert coord.lat == -5.8

    # ~2 km: passa do mínimo
    hass.states.async_set(
        "person.hudson", "not_home", {"latitude": -5.82, "longitude": -35.2}
    )
    await hass.async_block_till_done()
    assert (coord.lat, coord.lon) == (-5.82, -35.2)
    assert (erbs.lat, erbs.lon) == (-5.82, -35.2)

    # outro salto longo dentro dos 10 min: barrado pelo intervalo mínimo
    freezer.tick(timedelta(minutes=2))
    hass.states.async_set(
        "person.hudson", "not_home", {"latitude": -5.90, "longitude": -35.2}
    )
    await hass.async_block_till_done()
    assert coord.lat == -5.82

    # passados os 10 min, volta a seguir
    freezer.tick(timedelta(minutes=11))
    hass.states.async_set(
        "person.hudson", "not_home", {"latitude": -5.95, "longitude": -35.2}
    )
    await hass.async_block_till_done()
    assert coord.lat == -5.95


def _entry_monitores(hass, unique_id="uid_mon", **extra_ios):
    """Entry com um município monitorado + um monitor iOS."""
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": "wh_fixo"},
        unique_id=unique_id,
        subentries_data=[
            ConfigSubentryData(
                data={
                    "codigo_ibge": 3550308,
                    "monitorar": True,
                    "intervalo_municipio": 12,
                },
                subentry_type="municipio",
                title="São Paulo (SP)",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={
                    "paises": ["BR"],
                    "operadoras": [],
                    "incluir_beta": False,
                    **extra_ios,
                },
                subentry_type="monitor_ios",
                title="Monitor iOS",
                unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    return e


async def test_setup_roda_uma_vez_so(hass, mock_client):
    """Gravar monitor_id/secret não pode disparar reload no meio do setup.

    O listener de update é registrado no fim de async_setup_entry justamente
    por isso: `async_update_subentry` dispara os update_listeners. Se o
    `add_update_listener` for movido pra antes do loop de subentries, as duas
    gravações de monitor viram dois reloads e o setup roda de novo — o que
    aparece aqui como mais de um refresh do HealthCoordinator.
    """
    e = _entry_monitores(hass)
    client = mock_client
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()

    assert client.async_health.await_count == 1
    assert client.async_criar_monitor_ios.await_count == 1
    assert client.async_criar_monitor_cidade.await_count == 1


async def test_municipio_nao_recria_monitor_existente(hass, mock_client):
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": "wh_fixo"},
        unique_id="uid_mun",
        subentries_data=[
            ConfigSubentryData(
                data={
                    "codigo_ibge": 3550308,
                    "monitorar": True,
                    "intervalo_municipio": 12,
                    "monitor_id": "9f1c0001",
                    "monitor_secret": "whsec_ja_tem",
                },
                subentry_type="municipio",
                title="São Paulo (SP)",
                unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    client = mock_client
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    client.async_criar_monitor_cidade.assert_not_awaited()
    subentry = next(iter(e.subentries.values()))
    assert subentry.data["monitor_secret"] == "whsec_ja_tem"


async def test_sem_url_externa_vira_setup_retry(hass, mock_client):
    """Sem external_url e com monitor a provisionar: retentável, não SETUP_ERROR."""
    e = _entry_monitores(hass, unique_id="uid_nourl")
    client = mock_client
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            side_effect=NoURLAvailableError,
        ),
    ):
        assert not await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    assert e.state is ConfigEntryState.SETUP_RETRY
    client.async_criar_monitor_cidade.assert_not_awaited()


async def test_api_fora_do_ar_vira_setup_retry(hass, entry_completa, mock_client):
    """RMFError no primeiro refresh de coordinator: SETUP_RETRY."""
    client = mock_client
    client.async_health.side_effect = RMFError("502")
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert not await hass.config_entries.async_setup(entry_completa.entry_id)
        await hass.async_block_till_done()
    assert entry_completa.state is ConfigEntryState.SETUP_RETRY


async def test_erro_ao_criar_monitor_vira_setup_retry(hass, mock_client):
    """RMFError na criação do monitor: SETUP_RETRY, não SETUP_ERROR."""
    e = _entry_monitores(hass, unique_id="uid_mon_erro")
    client = mock_client
    client.async_criar_monitor_cidade.side_effect = RMFError("502")
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert not await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    assert e.state is ConfigEntryState.SETUP_RETRY


def _fluxos_reauth(hass):
    return [
        f
        for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if f["context"].get("source") == "reauth"
    ]


async def test_token_expirado_no_coordinator_abre_reauth(
    hass, entry_completa, mock_client
):
    client = mock_client
    client.async_health.side_effect = RMFAuthError("403")
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert not await hass.config_entries.async_setup(entry_completa.entry_id)
        await hass.async_block_till_done()
    assert entry_completa.state is ConfigEntryState.SETUP_ERROR
    assert _fluxos_reauth(hass)


async def test_token_expirado_ao_criar_monitor_abre_reauth(hass, mock_client):
    e = _entry_monitores(hass, unique_id="uid_mon_auth")
    client = mock_client
    client.async_criar_monitor_cidade.side_effect = RMFAuthError("403")
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert not await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    assert e.state is ConfigEntryState.SETUP_ERROR
    assert _fluxos_reauth(hass)


async def test_unload_libera_webhook_e_listener(hass, mock_client):
    """Unload precisa soltar de verdade o webhook e o listener da pessoa."""
    hass.states.async_set(
        "person.hudson", "home", {"latitude": -5.8, "longitude": -35.2}
    )
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": "wh_fixo"},
        unique_id="uid_unload",
        subentries_data=[
            ConfigSubentryData(
                data={
                    "modo": "pessoa",
                    "entity_id": "person.hudson",
                    "intervalo_cobertura": 30,
                    "intervalo_erbs": 6,
                    "max_geo": 25,
                },
                subentry_type="local",
                title="Hudson",
                unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    client = mock_client
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()

    coord = list(e.runtime_data.cobertura.values())[0]

    assert await hass.config_entries.async_unload(e.entry_id)
    await hass.async_block_till_done()

    # webhook desregistrado: registrar o mesmo id de novo não pode conflitar
    webhook.async_register(hass, "test", "outro", "wh_fixo", None)
    webhook.async_unregister(hass, "wh_fixo")

    # listener da pessoa desligado: deslocamento longo não mexe mais no coordinator
    hass.states.async_set(
        "person.hudson", "not_home", {"latitude": -6.5, "longitude": -35.2}
    )
    await hass.async_block_till_done()
    assert coord.lat == -5.8


async def test_monitor_ios_descontinuado_410_nao_trava_setup(hass, entry_completa, mock_client):
    """API passou a responder 410 pra novos monitores de iOS: a entry carrega
    mesmo assim (cobertura/município seguem) e abre um aviso nos Reparos."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.redes_moveis_fixas.api import RMFGoneError

    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    mock_client.async_criar_monitor_ios.side_effect = RMFGoneError("410")
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=mock_client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(entry_completa.entry_id)
        await hass.async_block_till_done()

    assert entry_completa.state is ConfigEntryState.LOADED
    subs = {s.subentry_type: s for s in entry_completa.subentries.values()}
    assert "monitor_id" not in subs["monitor_ios"].data
    assert subs["municipio"].data["monitor_id"] == "9f1c0001"
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"monitor_descontinuado_{subs['monitor_ios'].subentry_id}"
    )
    assert issue is not None and issue.translation_key == "monitor_descontinuado"
