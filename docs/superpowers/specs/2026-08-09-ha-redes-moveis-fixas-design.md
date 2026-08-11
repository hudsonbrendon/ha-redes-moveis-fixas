# ha-redes-moveis-fixas — Design

**Data:** 2026-08-09
**Status:** Aprovado
**API:** https://redesmoveisfixas.com/createapi (base `https://api.redesmoveisfixas.com`)

## Objetivo

Custom component do Home Assistant pra API RMF (Redes Móveis Fixas): cobertura móvel por operadora, ERBs próximas, resumo municipal e monitores por webhook (novas torres na cidade + carrier bundles do iOS). Padrão dos repos `ha-*` existentes do usuário (api/coordinator/entity/config_flow/tests/hacs.json).

## Decisões

| Decisão | Escolha |
|---|---|
| Modelo de config | **Hub + subentries** — 1 entry = token; subentries: Local, Município, Monitor iOS |
| Webhook | URL própria do usuário via `get_url(hass, external_url=True)` + `webhook.async_register` |
| Novidades | Event entities + evento `redes_moveis_fixas_novidade` no bus com payload cru |
| Cobertura | Zonas do HA **e** seguir pessoa (device_tracker) |
| Mapa | ERBs como `geo_location` (N máx. configurável, default 25, 0 = off) |
| Domain | `redes_moveis_fixas` |
| Repo | `ha-redes-moveis-fixas` |

## Estrutura

```
custom_components/redes_moveis_fixas/
  api.py            cliente aiohttp puro (sem HA): cobertura, estacoes, municipio, health, monitores CRUD; exceções próprias
  coordinator.py    CoberturaCoordinator | ErbsCoordinator | MunicipioCoordinator | HealthCoordinator | MonitoresCoordinator
  webhook.py        registro, verificação HMAC, dispatch por subentry
  config_flow.py    entry (token) + reauth + 3 subentry flows + options
  entity.py         base RMFEntity (device_info, disponibilidade)
  sensor.py  binary_sensor.py  event.py  geo_location.py
  services.py  services.yaml   3 actions com response_data
  repairs.py  diagnostics.py  const.py
  strings.json  translations/{en,pt-BR}.json
tests/            pytest + pytest-homeassistant-custom-component
hacs.json  pyproject.toml  README.md
```

Camadas: `api.py` não importa HA → coordinators traduzem erros (`UpdateFailed`, `ConfigEntryAuthFailed`) → entities só leem `coordinator.data`. Um `RMFClient` por entry (sessão de `async_get_clientsession`), compartilhado — cota é por token.

## Entidades

Nomenclatura: `<medida>_<prep>` PT-BR, sem repetir o local — o device (nome do
subentry, ou "API RMF" na entry) já carrega essa informação
(`_attr_has_entity_name = False`, nome completo PT-BR na entidade). Desde o
Home Assistant ≥ 2026.8, o core prefixa o entity_id gerado com o nome do
device automaticamente (`entity_id_parts` default passou a incluir
`DEVICE`); os IDs abaixo já refletem esse prefixo. Em cores mais antigos
(testado até 2026.2.x) o prefixo `<device>_` não aparece.

**Device "API RMF"** (entry):
- `binary_sensor.api_rmf_status` — connectivity via `/health`
- `sensor.api_rmf_base_de_cobertura_atualizada_em`, `sensor.api_rmf_base_de_estacoes_atualizada_em` — timestamps das dependências do `/health`

**Device por subentry Local** (zona ou pessoa; ex. "Casa" → prefixo `casa_`):
- `sensor.casa_cobertura_da_<operadora>` — dinâmico por operadora retornada; state = `score_percentual` (%), `state_class: measurement`; attrs: classificação, força de sinal por tecnologia (5G/4G/3G/2G)
- `sensor.casa_melhor_cobertura` — operadora com maior score
- `binary_sensor.casa_5g_disponivel` — alguma operadora com 5G
- `sensor.casa_erbs_por_perto` — `total_erbs` raio 5 km; attrs: contagem por operadora e por tecnologia
- `sensor.casa_distancia_da_erb_mais_proxima` — km; attrs: operadora, endereço, tecnologias, bandas
- `geo_location.casa_erb_*` — N ERBs mais próximas no mapa; attrs: operadora, tecnologias, bandas

**Device por subentry Município** (ex. "Uberlândia" → prefixo `uberlandia_`):
- `sensor.uberlandia_erbs` (celular), `sensor.uberlandia_estacoes` (total)
- `sensor.uberlandia_erbs_5g` + 4G/3G/2G — `state_class: measurement` (leitura pontual a cada atualização, não um acumulador — `total` geraria uma estatística de soma e trataria uma queda de contagem como reset); attrs: quebra por operadora
- `sensor.uberlandia_base_atualizada_em`
- `event.uberlandia_novas_torres` — event_types: `nova_erb`, `upgrade_tecnologia`; attrs do payload do webhook; um `async_write_ha_state()` por item da entrega (não um só no fim), senão itens 1..N-1 de uma entrega com várias novidades nunca aparecem no state machine
- `binary_sensor.uberlandia_monitor_ativo` — attrs: `falhas_seguidas`, `ultima_entrega`, `ultimo_erro`

**Device por subentry Monitor iOS**:
- `event.monitor_ios_novidades` — event_types: `nova`, `alterada`, `removida`; attrs: operadora, país, bundle from→to, recursos ±, rótulos ±, beta; mesmo write-por-item da entrega acima
- `sensor.monitor_ios_ultima_novidade` — timestamp da última entrega
- `binary_sensor.monitor_ios_monitor_ativo` — attrs: `falhas_seguidas`, `ultima_entrega`, `ultimo_erro`

Todo webhook válido também dispara `redes_moveis_fixas_novidade` no bus (payload cru + `subentry_id`).

## Coordinators e cotas

Cota por token, compartilhada entre subentries.

| Coordinator | Endpoint | Cota API | Intervalo default |
|---|---|---|---|
| Cobertura (por local) | `GET /api/cobertura` | 2.000/dia, 60/min | 30 min |
| ERBs (por local) | `GET /api/estacoes` | 500/dia, 20/min | 6 h |
| Município (por cidade) | `GET /api/municipios/{ibge}/resumo` | 5.000/dia, 120/min | 12 h |
| Health (entry) | `GET /health` (sem auth) | — | 15 min |
| Monitores (entry) | `GET /api/monitorar-*` | 200/dia, 20/min | 6 h |

4 locais + 2 cidades no default ≈ 230 req/dia. Intervalos definidos na criação da subentry; não há options flow para editá-los depois (ver "Config flow" abaixo) — mudar exige remover e recriar a subentry.

- `429` → `UpdateFailed` (backoff do DataUpdateCoordinator)
- `403` → `ConfigEntryAuthFailed` → reauth flow (token expira em 90 dias)

## Seguir pessoa

Subentry de pessoa escuta `async_track_state_change_event` do `person.X`. Refaz cobertura só se: moveu > 500 m (haversine vs. última consulta) **e** ≥ 10 min desde a última. Sem GPS/coords → coordinator não faz request (`lat`/`lon` None) e retorna `{}`; as entities ficam `unknown`, não `unavailable` (comportamento aceito, ver `tests/test_sensor.py::test_sensores_toleram_dados_vazios`).

## Webhook

- Um `webhook_id` por entry, registrado no `async_setup_entry`; URL de `get_url(hass, external_url=True)`.
- Validação: `X-RMF-Signature` = HMAC-SHA256(`timestamp + "." + corpo cru`, chave = `secret` do monitor). Tolerância de 5 min no timestamp (anti-replay). Inválido → `401` + log debug (endpoint público/sem auth: warning a cada tentativa de terceiro inflaria o log).
- Responde `200` imediato; dispatch por `evento`: `novidades.cidade` → subentry do IBGE; `novidades.ios` → subentry do monitor.
- `secret` guardado em `subentry.data`; redigido no diagnostics junto com o token.
- Criar subentry com monitor → POST na API; remover subentry → DELETE.
- External_url mudou → repair issue + fix flow recria monitores com URL nova.
- Sem URL pública resolvível (`NoURLAvailableError`): degrada em vez de bloquear. Se nenhuma subentry precisa provisionar um monitor novo, a entry carrega normalmente e só a varredura de órfãos é pulada (log em debug); se uma subentry precisa provisionar e não há URL, o setup levanta `ConfigEntryNotReady` e tenta de novo depois.

## Repairs

`MonitoresCoordinator` detecta `ativo: false` (API desativa após 10 falhas seguidas) → repair issue "Monitor desativado" com fix flow que re-registra o monitor.

## Actions

Todas com `supports_response`:

| Action | Entrada | Saída |
|---|---|---|
| `redes_moveis_fixas.consultar_cobertura` | lat/lon **ou** entity_id de zona/pessoa | payload de cobertura |
| `redes_moveis_fixas.buscar_estacoes` | lat/lon + filtros (operadora, tecnologia, banda, limite) | lista de ERBs |
| `redes_moveis_fixas.resumo_do_municipio` | código IBGE (7 dígitos) | resumo municipal |

## Config flow

**Entry:** token → valida com `/health` + GET listagem de monitores → `unique_id` = hash do token. Reauth reusa o step.

**Subentries** (menu "Adicionar"):
- **Local** — `SelectSelector` zona ou pessoa; opções: intervalos (cobertura, ERBs), N máx. de geo_location (default 25, 0 = off)
- **Município** — IBGE 7 dígitos, validado com GET `/resumo` (nome vira título); checkbox "monitorar novas torres"
- **Monitor iOS** — países (multi, default `["BR"]`), operadoras (opcional), `incluir_beta`

Sem options flow: intervalos e N máx. de geo_location são fixados na criação da subentry; editar exige remover e recriar.

## Testes

pytest + `pytest-homeassistant-custom-component`; fixtures = JSONs de exemplo da doc da API.

- `test_api.py` — parse dos endpoints, 403/429/timeout (aioresponses)
- `test_config_flow.py` — entry, reauth, 3 subentry flows, IBGE/token inválidos
- `test_coordinator.py` — intervalos, backoff 429, auth failed 403
- `test_webhook.py` — assinatura válida/inválida/timestamp velho, dispatch correto, evento no bus
- `test_sensor.py` / `test_event.py` / `test_geo_location.py` — estados a partir das fixtures
- `test_repairs.py` — `ativo: false` → issue; fix flow recria

## Empacotamento

- `manifest.json`: `iot_class: cloud_polling`, `dependencies: ["webhook"]`, `integration_type: hub`
- `hacs.json`, `strings.json` + `translations/pt-BR.json` e `en.json`
- `diagnostics.py` com redação de token/secret
- ruff (config dos outros repos ha-*), README com instalação HACS

## Fora de escopo (YAGNI)

- `device_tracker` da ERB mais próxima
- Botão de refresh (existe `homeassistant.update_entity`)
- Sensor de licenciamento vencendo
- Relay pra HA sem exposição (usuário tem external_url própria)
