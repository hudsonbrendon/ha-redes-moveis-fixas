# Entity naming fix — report

## Version landed on

- `pytest-homeassistant-custom-component` bumped from `>=0.13.230` to `>=0.13.355`
  in `requirements_test.txt`. This installs **Home Assistant 2026.8.1 exactly**,
  matching the user's production core (confirmed: `import homeassistant.const;
  print(__version__)` → `2026.8.1` in the rebuilt `.venv`).
- **The `.venv` was rebuilt on Python 3.14** (`/opt/homebrew/opt/python@3.14`),
  not 3.13. Reason: PHACC releases that pin `homeassistant==2026.8.x` (0.13.317
  through at least 0.13.355) all declare `Requires-Python >=3.14`. Under Python
  3.13, `pip index versions` silently filters those out and reports 0.13.316
  (→ HA 2026.2.3) as "latest" — that's a real trap, not a mirror gap: the
  packages exist on PyPI, `pip` just hides Python-incompatible releases from
  the listing. Recreating the venv with `python3.14 -m venv --clear .venv` and
  reinstalling made `pytest-homeassistant-custom-component==0.13.355` resolve
  cleanly.
- `hacs.json`'s `homeassistant` key raised from `2025.7.0` to `2026.8.0`, since
  that's the floor now actually exercised by the test suite, and the naming
  behavior this fix depends on (device-name entity_id prefixing) is a
  2026.8-era core change — declaring support for older cores would be false
  advertising once the suite no longer verifies them.
- `pyproject.toml`'s `ruff` `target-version` was left at `py313` — untouched,
  since it doesn't affect correctness and wasn't asked for.

## What the version bump broke, and the fix

Bumping to real aiohttp 3.14.3 (pinned by HA 2026.8.1) broke all 14 tests in
`test_api.py` plus one in `test_config_flow.py` with
`TypeError: ClientResponse.__init__() missing 1 required keyword-only
argument: 'stream_writer'`. Root cause: `aioresponses` 0.7.9 — the latest
release on PyPI and on GitHub, there is no newer version — still constructs
`aiohttp.client_reqrep.ClientResponse` without passing `stream_writer`, which
newer aiohttp made mandatory. This is an unfixed upstream incompatibility
between `aioresponses` and current `aiohttp`, not something this repo's code
caused.

Fix: a small, clearly-commented compatibility shim in `tests/conftest.py`
that monkeypatches `ClientResponse.__init__` to default `stream_writer` to
`Mock(output_size=0)` only when the caller omits it (real aiohttp code always
passes its own, so production code paths are unaffected). Marked with a
`ponytail:` comment noting the upstream issue and the upgrade-away condition
(drop it once `aioresponses` ships a fix). All 22 API/config-flow tests pass
with the shim.

No other unrelated breakage — the remaining 19 failures after the version
bump were all entity_id assertion mismatches from the renaming work itself
(task 2/3 below), not from the core bump.

## Root cause of the production bug (confirmed empirically)

Read `homeassistant/helpers/entity_registry.py` in the actual installed
2026.8.1 package: `_async_generate_entity_id` now defaults
`parts = (EntityNamePart.AREA, EntityNamePart.DEVICE, EntityNamePart.ENTITY)`
for **every** entity, regardless of `has_entity_name`. This is a real core
behavior change from the 2026.2.3 era (where `object_id_base` was only
device-prefixed when `has_entity_name=True`). It also strips a leading
device-name prefix from the entity's own name before recombining
(`_async_strip_prefix_from_entity_name`), which is why e.g. old name
"Monitor iOS ativo" on device "Monitor iOS" produced `monitor_ios_ativo`
(not a doubled `monitor_ios_monitor_ios_ativo`) even before this fix.

Confirmed by running the untouched test suite against real 2026.8.1 *before*
making any naming changes — it reproduced the exact IDs from the bug report:
`binary_sensor.api_rmf_status_da_api_rmf`,
`sensor.casa_cobertura_da_vivo_em_casa`, etc.

## Entity name / entity_id changes (before → after)

All under `_attr_has_entity_name = False`, `unique_id` unchanged. IDs below
are what `hass.states.get(...)` actually returns from the test suite running
against HA 2026.8.1 (verified via `pytest -s | grep "Registered new"`, not
guessed).

| File | Old name | New name | Old entity_id (2026.8.1) | New entity_id (2026.8.1) |
|---|---|---|---|---|
| binary_sensor.py | `Status da API RMF` | `Status` | `binary_sensor.api_rmf_status_da_api_rmf` | `binary_sensor.api_rmf_status` |
| binary_sensor.py | `5G disponível em {título}` | `5G disponível` | `binary_sensor.casa_5g_disponivel_em_casa` | `binary_sensor.casa_5g_disponivel` |
| binary_sensor.py | `Monitor de {título} ativo` | `Monitor ativo` | `binary_sensor.sao_paulo_sp_monitor_de_sao_paulo_sp_ativo` | `binary_sensor.sao_paulo_sp_monitor_ativo` |
| binary_sensor.py | `Monitor iOS ativo` | `Monitor ativo` | `binary_sensor.monitor_ios_ativo` | `binary_sensor.monitor_ios_monitor_ativo` |
| sensor.py | `Cobertura da {operadora} em {título}` | `Cobertura da {operadora}` | `sensor.casa_cobertura_da_vivo_em_casa` | `sensor.casa_cobertura_da_vivo` |
| sensor.py | `Melhor cobertura em {título}` | `Melhor cobertura` | `sensor.casa_melhor_cobertura_em_casa` | `sensor.casa_melhor_cobertura` |
| sensor.py | `ERBs por perto de {título}` | `ERBs por perto` | `sensor.casa_erbs_por_perto_de_casa` | `sensor.casa_erbs_por_perto` |
| sensor.py | `Distância da ERB mais próxima de {título}` | `Distância da ERB mais próxima` | `sensor.casa_distancia_da_erb_mais_proxima_de_casa` | `sensor.casa_distancia_da_erb_mais_proxima` |
| sensor.py | `{rótulo} em {título}` (ERBs/Estações) | `{rótulo}` | `sensor.sao_paulo_sp_erbs_em_sao_paulo_sp` / `..._estacoes_em_...` | `sensor.sao_paulo_sp_erbs` / `sensor.sao_paulo_sp_estacoes` |
| sensor.py | `ERBs {tec} em {título}` | `ERBs {tec}` | `sensor.sao_paulo_sp_erbs_5g_em_sao_paulo_sp` (+4g/3g/2g) | `sensor.sao_paulo_sp_erbs_5g` (+4g/3g/2g) |
| sensor.py | `Base de {título} atualizada em` | `Base atualizada em` | `sensor.sao_paulo_sp_base_de_sao_paulo_sp_atualizada_em` | `sensor.sao_paulo_sp_base_atualizada_em` |
| sensor.py | `Última novidade do iOS` | `Última novidade` | `sensor.monitor_ios_ultima_novidade_do_ios` | `sensor.monitor_ios_ultima_novidade` |
| sensor.py | `Base de {dependência} atualizada em` (entry device) | *unchanged* | `sensor.api_rmf_base_de_cobertura_atualizada_em` | *unchanged* (never had redundant location text) |
| event.py | `Novas torres em {título}` | `Novas torres` | `event.sao_paulo_sp_novas_torres_em_sao_paulo_sp` | `event.sao_paulo_sp_novas_torres` |
| event.py | `Novidades do iOS` | `Novidades` | `event.monitor_ios_novidades_do_ios` | `event.monitor_ios_novidades` |
| geo_location.py | `ERB {operadora} {id}` | *unchanged* | `geo_location.casa_erb_claro_1234567` | *unchanged* (name never contained the location) |

## Tests

- Updated `tests/test_sensor.py`, `tests/test_binary_sensor.py`,
  `tests/test_event.py` to assert the new entity_ids — every string was
  swapped to the value actually produced by the current HA 2026.8.1 test run
  (grepped `"Registered new"` log lines from `pytest -s`), not inferred.
- `tests/test_geo_location.py`, `tests/test_repairs.py`,
  `tests/test_diagnostics.py`, `tests/test_webhook.py`,
  `tests/test_services.py`, `tests/test_subentry_flows.py`,
  `tests/test_init.py`, `tests/test_api.py`, `tests/test_config_flow.py`,
  `tests/test_const.py`, `tests/test_coordinator.py` needed no changes.
- Final result: `134 passed` (same count as before — no tests added or
  removed, only assertions/fixtures updated), `ruff check` and
  `ruff format --check` both clean.

## Docs updated

- `README.md`: entity table rewritten with `<device>_`-prefixed IDs and a new
  callout explaining the HA ≥ 2026.8 device-prefixing behavior; the
  "Operadora nova exige reload" note's example ID updated too.
- `docs/superpowers/specs/2026-08-09-ha-redes-moveis-fixas-design.md`:
  "Entidades" section rewritten with the new IDs and a note on the
  `entity_id_parts` core change. `docs/superpowers/plans/...` (the original
  implementation plan, not the design spec) was **left untouched** — it's a
  point-in-time historical record of what was planned/built, out of the
  scope the task named ("the design spec ... where it lists entity IDs").

## Things I could not close

1. **The PyPI mirror trap.** Under Python 3.13 (the venv's original
   interpreter), `pip index versions pytest-homeassistant-custom-component`
   reports `0.13.316` (→ HA 2026.2.3) as latest — every release that actually
   pins HA 2026.8.x requires Python ≥3.14 and gets silently hidden from that
   listing. I found this by checking GitHub tags directly and diffing against
   what `pip` would install. Worth knowing if this repo's CI still runs on
   3.13 elsewhere: it would silently re-drift back to testing against
   HA 2026.2.3 with a misleadingly-succeeding `pip install -U`.
2. **`aioresponses` is unmaintained against current aiohttp.** The shim in
   `tests/conftest.py` works today but is a workaround for someone else's bug,
   not a fix. If a future aiohttp release changes `ClientResponse.__init__`
   again, this shim may need adjusting or the test suite should migrate to
   `pytest_homeassistant_custom_component`'s own `aioclient_mock` fixture
   (already a transitive dependency, no new package needed) instead of
   `aioresponses`. Left as-is per the "smallest fix that gets the suite green"
   framing of the task — flagging as a known future maintenance cost, not
   fixed further.
3. Everything else in the task (naming, tests, docs, hacs.json, lint) is
   fully done and verified — no other open items.
