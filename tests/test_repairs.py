"""Testes de repairs (monitor inativo) e varredura de órfãos."""

import homeassistant.helpers.issue_registry as ir

from custom_components.redes_moveis_fixas.repairs import MonitorInativoFlow

from .conftest import load_fixture
from .test_sensor import _setup


def _sub_ios(entry):
    return next(
        s for s in entry.subentries.values() if s.subentry_type == "monitor_ios"
    )


def _marcar_monitor_ios(entry, monitor_id="3ab7f001", secret="s"):
    """Simula subentry ios já provisionada (monitor_id/secret gravados)."""
    sub = _sub_ios(entry)
    novo = {**sub.data, "monitor_id": monitor_id, "monitor_secret": secret}
    object.__setattr__(sub, "data", novo)


async def test_issue_quando_monitor_inativo(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    lista = load_fixture("monitores_ios_lista.json")["dados"]
    lista[0]["ativo"] = False
    lista[0]["falhas_seguidas"] = 10

    def _listar(tipo):
        return lista if tipo == "ios" else []

    mock_client.async_listar_monitores.side_effect = _listar
    # subentry ios já com monitor_id igual ao da listagem
    _marcar_monitor_ios(entry_completa)

    await _setup(hass, entry_completa, mock_client)

    registry = ir.async_get(hass)
    sub_ios = _sub_ios(entry_completa)
    issue = registry.async_get_issue(
        "redes_moveis_fixas", f"monitor_inativo_{sub_ios.subentry_id}"
    )
    assert issue is not None
    assert issue.is_fixable
    assert issue.data == {
        "entry_id": entry_completa.entry_id,
        "subentry_id": sub_ios.subentry_id,
    }


async def test_issue_quando_monitor_sumiu(hass, entry_completa, mock_client):
    """A API pode apagar o monitor de vez (não só marcar `ativo: false`)."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    _marcar_monitor_ios(entry_completa)

    # listagem vazia pros dois tipos: o id "3ab7f001" sumiu de vez
    mock_client.async_listar_monitores.side_effect = lambda tipo: []

    await _setup(hass, entry_completa, mock_client)

    registry = ir.async_get(hass)
    sub_ios = _sub_ios(entry_completa)
    issue = registry.async_get_issue(
        "redes_moveis_fixas", f"monitor_inativo_{sub_ios.subentry_id}"
    )
    assert issue is not None


async def test_issue_removida_quando_saudavel(hass, entry_completa, mock_client):
    """Issue de uma queda anterior some assim que o monitor volta a `ativo`."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    lista = load_fixture("monitores_ios_lista.json")["dados"]
    lista[0]["ativo"] = True  # saudável desde o primeiro refresh

    def _listar(tipo):
        return lista if tipo == "ios" else []

    mock_client.async_listar_monitores.side_effect = _listar
    _marcar_monitor_ios(entry_completa)

    sub_ios = _sub_ios(entry_completa)
    issue_id = f"monitor_inativo_{sub_ios.subentry_id}"
    registry = ir.async_get(hass)
    ir.async_create_issue(
        hass,
        "redes_moveis_fixas",
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="monitor_inativo",
        data={"entry_id": entry_completa.entry_id, "subentry_id": sub_ios.subentry_id},
    )
    assert registry.async_get_issue("redes_moveis_fixas", issue_id) is not None

    await _setup(hass, entry_completa, mock_client)

    assert registry.async_get_issue("redes_moveis_fixas", issue_id) is None


async def test_orfao_removido(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    orfao = {
        "id": "deadbeef",
        "url": "https://ha.example.com/api/webhook/wh_fixo",
        "ativo": True,
        "falhas_seguidas": 0,
        "ultima_entrega": None,
        "ultimo_erro": None,
    }

    def _listar(tipo):
        return [orfao] if tipo == "cidade" else []

    mock_client.async_listar_monitores.side_effect = _listar
    await _setup(hass, entry_completa, mock_client)

    mock_client.async_remover_monitor.assert_any_await("cidade", "deadbeef")


async def test_orfao_url_diferente_nao_removido(hass, entry_completa, mock_client):
    """Guarda de segurança: monitor de OUTRA instalação/entry nunca é apagado.

    Mesmo sem dono (id não reivindicado por nenhuma subentry desta entry), um
    monitor cuja `url` não é a nossa não pode ser tocado — senão a varredura
    de órfãos vira uma arma de apagar monitor alheio.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    de_outra_instalacao = {
        "id": "outroha0",
        "url": "https://outra-instalacao.example.com/api/webhook/xyz",
        "ativo": True,
        "falhas_seguidas": 0,
        "ultima_entrega": None,
        "ultimo_erro": None,
    }

    def _listar(tipo):
        return [de_outra_instalacao] if tipo == "cidade" else []

    mock_client.async_listar_monitores.side_effect = _listar
    await _setup(hass, entry_completa, mock_client)

    mock_client.async_remover_monitor.assert_not_awaited()


async def test_fix_flow_recria_monitor(hass, entry_completa, mock_client):
    """Confirm step: apaga o monitor morto e cria um novo, id/secret novos.

    A subentry entra com o monitor "3ab7f001" (marcado inativo). O flow deve
    chamar DELETE no velho, POST num novo, e persistir o id/secret novos —
    numa única passagem, sem deixar a subentry num intervalo sem nenhum dos
    dois (ver análise de "estado pela metade" no relatório).
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    lista = load_fixture("monitores_ios_lista.json")["dados"]
    lista[0]["ativo"] = False
    mock_client.async_listar_monitores.side_effect = (
        lambda tipo: lista if tipo == "ios" else []
    )
    _marcar_monitor_ios(entry_completa)
    mock_client.async_criar_monitor_ios.return_value = {
        "id": "novoid02",
        "secret": "whsec_novo",
    }

    await _setup(hass, entry_completa, mock_client)
    mock_client.async_criar_monitor_ios.reset_mock()

    sub_ios = _sub_ios(entry_completa)
    flow = MonitorInativoFlow(
        {"entry_id": entry_completa.entry_id, "subentry_id": sub_ios.subentry_id}
    )
    flow.hass = hass
    result = await flow.async_step_confirm({})

    assert result["type"] == "create_entry"
    mock_client.async_remover_monitor.assert_any_await("ios", "3ab7f001")
    mock_client.async_criar_monitor_ios.assert_awaited_once()

    sub_ios = _sub_ios(entry_completa)
    assert sub_ios.data["monitor_id"] == "novoid02"
    assert sub_ios.data["monitor_secret"] == "whsec_novo"
