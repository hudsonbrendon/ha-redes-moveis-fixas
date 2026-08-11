"""Testes de repairs (monitor inativo) e varredura de órfãos."""

from unittest.mock import patch

import homeassistant.helpers.issue_registry as ir
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.helpers.network import NoURLAvailableError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.const import DOMAIN
from custom_components.redes_moveis_fixas.repairs import MonitorInativoFlow

from .conftest import load_fixture
from .test_sensor import _setup

WEBHOOK_URL = "https://ha.example.com/api/webhook/wh_fixo"


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


async def test_sem_issue_falsa_apos_provisionar_pela_primeira_vez(
    hass, entry_completa, mock_client
):
    """MonitoresCoordinator atualiza ANTES do loop de provisionamento.

    Sem reavaliar depois de criar os monitores, um monitor criado nesta
    própria passagem de setup pareceria "sumido" pro coordinator (cujo
    snapshot é de antes da criação) e abriria uma issue falsa logo no
    primeiro setup — que só sumiria até 6h depois (INTERVALO_MONITORES).
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    criado = {"ios": False, "cidade": False}

    def _criar_ios(*_a, **_kw):
        criado["ios"] = True
        return {"id": "3ab7f001", "secret": "whsec_test_1d90aa"}

    def _criar_cidade(*_a, **_kw):
        criado["cidade"] = True
        return {"id": "9f1c0001", "secret": "whsec_cidade_aa"}

    mock_client.async_criar_monitor_ios.side_effect = _criar_ios
    mock_client.async_criar_monitor_cidade.side_effect = _criar_cidade

    def _listar(tipo):
        base = {
            "ativo": True,
            "falhas_seguidas": 0,
            "ultima_entrega": None,
            "ultimo_erro": None,
        }
        if tipo == "ios" and criado["ios"]:
            return [{"id": "3ab7f001", "url": WEBHOOK_URL, **base}]
        if tipo == "cidade" and criado["cidade"]:
            return [{"id": "9f1c0001", "url": WEBHOOK_URL, **base}]
        return []

    mock_client.async_listar_monitores.side_effect = _listar

    await _setup(hass, entry_completa, mock_client)

    registry = ir.async_get(hass)
    for sub in entry_completa.subentries.values():
        if sub.subentry_type in ("monitor_ios", "municipio"):
            issue = registry.async_get_issue(
                "redes_moveis_fixas", f"monitor_inativo_{sub.subentry_id}"
            )
            assert issue is None, f"issue falsa em {sub.subentry_type}: {issue}"


async def test_issue_de_subentry_removida_e_limpa(hass, entry_completa, mock_client):
    """Remover uma subentry não tem hook próprio no HA (nota do design doc).

    Uma issue `monitor_inativo_{subentry_id}` cuja subentry já não existe
    mais tem que ser varrida no próximo setup, não vazar pra sempre.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    registry = ir.async_get(hass)
    issue_id = "monitor_inativo_subentry-que-nao-existe-mais"
    ir.async_create_issue(
        hass,
        "redes_moveis_fixas",
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="monitor_inativo",
        data={
            "entry_id": entry_completa.entry_id,
            "subentry_id": "subentry-que-nao-existe-mais",
        },
    )
    assert registry.async_get_issue("redes_moveis_fixas", issue_id) is not None

    await _setup(hass, entry_completa, mock_client)

    assert registry.async_get_issue("redes_moveis_fixas", issue_id) is None


async def test_orfao_removido(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    orfao = {
        "id": "deadbeef",
        "url": WEBHOOK_URL,
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
    """Guarda de segurança: monitor de OUTRO webhook nunca é apagado.

    Mesmo hostname que o nosso (`ha.example.com`) e mesmo formato de URL —
    só o segmento do webhook id no fim muda (`wh_outro` vs. `wh_fixo`). Isso
    só passa se a comparação for igualdade exata de string; um match por
    prefixo/hostname (em vez da URL inteira) deixaria passar isto e apagaria
    monitor de outra entry/instalação que só compartilhe o domínio.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    de_outro_webhook = {
        "id": "outroha0",
        "url": "https://ha.example.com/api/webhook/wh_outro",
        "ativo": True,
        "falhas_seguidas": 0,
        "ultima_entrega": None,
        "ultimo_erro": None,
    }

    def _listar(tipo):
        return [de_outro_webhook] if tipo == "cidade" else []

    mock_client.async_listar_monitores.side_effect = _listar
    await _setup(hass, entry_completa, mock_client)

    mock_client.async_remover_monitor.assert_not_awaited()


async def test_orfao_sem_id_nao_derruba_setup(hass, entry_completa, mock_client):
    """Registro sem `id` na listagem: pulado, não estoura KeyError no setup."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    sem_id = {
        "url": WEBHOOK_URL,
        "ativo": True,
        "falhas_seguidas": 0,
        "ultima_entrega": None,
        "ultimo_erro": None,
    }

    def _listar(tipo):
        return [sem_id] if tipo == "cidade" else []

    mock_client.async_listar_monitores.side_effect = _listar
    await _setup(hass, entry_completa, mock_client)  # não pode levantar KeyError

    mock_client.async_remover_monitor.assert_not_awaited()


async def test_sem_url_e_sem_provisionar_carrega(hass, mock_client):
    """Regressão do Task 7: sem external_url mas sem NADA pra provisionar,
    a entry precisa carregar mesmo assim — a varredura de órfãos precisa de
    URL só pra si mesma; ela não pode travar o setup inteiro por isso (Task
    7 já tinha corrigido exatamente essa laziness pro provisionamento).
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": "wh_fixo"},
        unique_id="uid_sem_url",
        subentries_data=[
            ConfigSubentryData(
                data={
                    "modo": "zona",
                    "entity_id": "zone.home",
                    "intervalo_cobertura": 30,
                    "intervalo_erbs": 6,
                    "max_geo": 25,
                },
                subentry_type="local",
                title="Casa",
                unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    with (
        patch(
            "custom_components.redes_moveis_fixas.RMFClient",
            return_value=mock_client,
        ),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            side_effect=NoURLAvailableError,
        ),
    ):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    assert e.state is ConfigEntryState.LOADED
    # só as 2 chamadas do MonitoresCoordinator (cidade+ios); a varredura de
    # órfãos foi pulada (sem URL), então não soma outras 2 por cima.
    assert mock_client.async_listar_monitores.await_count == 2


async def test_fix_flow_recria_monitor(hass, entry_completa, mock_client):
    """Confirm step: apaga o monitor morto; o reload agendado recria.

    A subentry entra com o monitor "3ab7f001" (marcado inativo). O flow só
    faz DELETE no velho e tira monitor_id/secret da subentry — isso agenda
    um reload (update listener), e é o próprio `async_setup_entry` desse
    reload que reprovisiona (idempotente: cria só porque não tem
    monitor_id). Ver relatório pra análise de por que isto não cria dois
    monitores em paralelo.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    lista = load_fixture("monitores_ios_lista.json")["dados"]
    lista[0]["ativo"] = False
    mock_client.async_listar_monitores.side_effect = lambda tipo: (
        lista if tipo == "ios" else []
    )
    _marcar_monitor_ios(entry_completa)
    mock_client.async_criar_monitor_ios.return_value = {
        "id": "novoid02",
        "secret": "whsec_novo",
    }

    # Patches ficam de pé durante TODO o teste (não só o `_setup` inicial):
    # o reload disparado pelo flow também passa por RMFClient/webhook_url.
    with (
        patch(
            "custom_components.redes_moveis_fixas.RMFClient",
            return_value=mock_client,
        ),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value=WEBHOOK_URL,
        ),
    ):
        assert await hass.config_entries.async_setup(entry_completa.entry_id)
        await hass.async_block_till_done()

        mock_client.async_criar_monitor_ios.reset_mock()

        sub_ios = _sub_ios(entry_completa)
        flow = MonitorInativoFlow(
            {"entry_id": entry_completa.entry_id, "subentry_id": sub_ios.subentry_id}
        )
        flow.hass = hass
        result = await flow.async_step_confirm({})
        assert result["type"] == "create_entry"

        mock_client.async_remover_monitor.assert_any_await("ios", "3ab7f001")

        # a recriação em si só acontece no reload agendado pelo strip-write
        await hass.async_block_till_done()

    mock_client.async_criar_monitor_ios.assert_awaited_once()
    sub_ios = _sub_ios(entry_completa)
    assert sub_ios.data["monitor_id"] == "novoid02"
    assert sub_ios.data["monitor_secret"] == "whsec_novo"


async def test_fix_flow_aborta_se_entry_removida(hass, entry_completa):
    """Blocking 3: a issue sobrevive à entry. Sem o guard, `entry is None`
    faz `entry.subentries[...]` estourar AttributeError puro (o "Unknown
    error occurred" do relatório) em vez de abortar limpo.
    """
    flow = MonitorInativoFlow(
        {"entry_id": "entry-que-nao-existe-mais", "subentry_id": "qualquer"}
    )
    flow.hass = hass
    result = await flow.async_step_confirm({})
    assert result["type"] == "abort"
    assert result["reason"] == "entry_not_found"


async def test_fix_flow_aborta_se_entry_descarregada(hass, entry_completa, mock_client):
    """`ConfigEntry.async_unload` apaga `entry.runtime_data` (object.__delattr__
    no core) — sem o guard de estado, `entry.runtime_data.client` estoura
    AttributeError pra uma entry NOT_LOADED (ex.: falhou reload após o
    monitor cair) mas com a issue ainda aberta no dashboard.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    _marcar_monitor_ios(entry_completa)
    await _setup(hass, entry_completa, mock_client)

    sub_ios = _sub_ios(entry_completa)
    assert await hass.config_entries.async_unload(entry_completa.entry_id)
    await hass.async_block_till_done()

    flow = MonitorInativoFlow(
        {"entry_id": entry_completa.entry_id, "subentry_id": sub_ios.subentry_id}
    )
    flow.hass = hass
    result = await flow.async_step_confirm({})
    assert result["type"] == "abort"
    assert result["reason"] == "entry_not_loaded"


async def test_fix_flow_aborta_se_subentry_sumiu(hass, entry_completa, mock_client):
    """Guarda irmã: entry viva e carregada, mas a subentry específica já
    não existe mais (removida entre a issue abrir e o usuário clicar Fix).
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    flow = MonitorInativoFlow(
        {
            "entry_id": entry_completa.entry_id,
            "subentry_id": "subentry-que-nao-existe-mais",
        }
    )
    flow.hass = hass
    result = await flow.async_step_confirm({})
    assert result["type"] == "abort"
    assert result["reason"] == "subentry_not_found"


async def test_remove_entry_limpa_issues_de_monitor(hass, entry_completa, mock_client):
    """async_remove_entry apagava só os monitores remotos; a issue local
    (`monitor_inativo_{subentry_id}`) ficava pra sempre no dashboard porque
    nada mais chama `_checar_monitores` por uma entry que já não existe.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    _marcar_monitor_ios(entry_completa)
    await _setup(hass, entry_completa, mock_client)

    registry = ir.async_get(hass)
    sub_ios = _sub_ios(entry_completa)
    issue_id = f"monitor_inativo_{sub_ios.subentry_id}"
    ir.async_create_issue(
        hass,
        "redes_moveis_fixas",
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="monitor_inativo",
        data={
            "entry_id": entry_completa.entry_id,
            "subentry_id": sub_ios.subentry_id,
        },
    )
    assert registry.async_get_issue("redes_moveis_fixas", issue_id) is not None

    with patch(
        "custom_components.redes_moveis_fixas.RMFClient", return_value=mock_client
    ):
        assert await hass.config_entries.async_remove(entry_completa.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get_issue("redes_moveis_fixas", issue_id) is None
