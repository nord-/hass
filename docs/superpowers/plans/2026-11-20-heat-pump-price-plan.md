# Heat Pump Price Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the reactive p75 heat-pump block with a once-a-day plan that places bounded blocks on tomorrow's most expensive windows.

**Architecture:** A `python_script` computes tomorrow's plan (budget from the SMHI forecast and indoor p10, exact interval DP over 96 quarters) and writes it to one of two `input_text` slots. A template binary sensor reads the slot dated today; an automation makes `switch.varmepumpen_a` follow it. Helpers, sensors and slots live in a YAML package so everything is in git.

**Tech Stack:** Home Assistant YAML (package, template, statistics, automations), HA `python_script` (RestrictedPython), pytest + RestrictedPython + jinja2 for local tests.

**Spec:** `docs/superpowers/specs/2026-11-20-heat-pump-price-plan-design.md`

## Global Constraints

- Code comments, docstrings, commit messages: English. UI names, card copy: Swedish (copy given verbatim below).
- Line endings: leave them to git (`core.autocrlf=true`). Do not convert files with `sed -i`.
- Spaces, no tabs. Conventional commits (`feat:`, `test:`, `fix:`, `docs:`). No AI attribution, no `Claude-Session` trailer.
- Entity ids come from `slugify(name)`; set `unique_id` to the same slug.
- Every `| float` / `| int` in templates has a default.
- No notifications anywhere in this feature.
- Never record the HA version as a fact about the installation; read it live (`GET http://hassio.local:8123/api/config` → `version`, token in `$HA_TOKEN`). Exempt: the sandbox mirror's provenance comment and the `RestrictedPython==` pin in Task 1, which name the tag they were copied from.
- Spot prices: SEK/kWh, `raw_tomorrow` of `sensor.nordpool_kwh_se3_sek_3_095_0`.
- Fixed constants (in the script): min block 4 quarters (1 h); gap after a block of L quarters = `max(4, ceil(L / 2))`; shifted excess `e[q] = price[q] − mean − 0.10`, a block needs `sum(e) > 1e-9`; laundry slope `c_laundry = clamp(1 − (full − p10) / 1.0, 0, 1)`; anchors −7.5 / −2.5 / +2.5 / +7.5 °C; 6 coldest hours; ≥ 18 forecast entries; quarter rounding `floor(x * 4 + 1e-9)`.
- Built-in helper defaults: block_cold 1, block_chilly 3, block_mild 4, block_warm 6 (h); budget_factor 2.0; laundry_full_p10 22.0; kitchen_floor_p10 21.0.
- **Plan string grammar** (used by Tasks 2, 3, 4, 6):
  - `YYYY-MM-DD <blocks>|t=<1 dec>;l=<2 dec>;k=<2 dec>;c=<2 dec>;m=<2 dec>;b=<2 dec>` — `m`, `b` in hours.
  - `<blocks>`: comma-separated `HH:MM-HH:MM`, local, `24:00` = end of day; may be empty (`2026-11-21 |…`).
  - DST day: `YYYY-MM-DD |t=na;l=na;k=na;c=na;m=0.00;b=0.00` — readers show `na` as `–`.
  - A slot may also hold `""`, `unknown`, `unavailable` or hand-edited garbage; readers treat anything that does not start with a valid `YYYY-MM-DD ` as "no plan" and skip malformed block pieces.

## Review Focus

1. `raw_tomorrow` `start`/`end` as UTC-aware `datetime` objects — must be converted with `dt_util.as_local` before comparing with local midnight; expected: same plan as local datetimes. Test in Task 2.
2. Forecast covering 58 h — only entries with local datetime in [tomorrow 00:00, day after 00:00) count. Test in Task 2.
3. A helper state that is a non-numeric string (`unavailable`, `abc`) — built-in default, never a crash. Test in Task 2.
4. A slot hand-edited to garbage (`hello`, `unknown`, or today's date followed by malformed blocks) — "no plan" for slot choice and carry-over, no exception. Tests in Tasks 3 and 4.
5. `raw_tomorrow` still holding the previous day's prices (a tick just after midnight, before Nordpool rolls over) — the date check rejects it, nothing written. Test in Task 2.

## Execution tracks

- **Main track:** Task 1 → Task 2 → Task 3.
- **Side track** (isolated worktree, first step `git reset --hard <the commit that adds this revision of the plan>`): Task 4 → Task 5 → Task 6. It consumes only the entity ids and the plan string grammar fixed above. Task 4 adds `tests/test_templates.py` and appends `jinja2` to `tests/requirements.txt`; expect a one-line conflict in `tests/requirements.txt` when cherry-picking.
- Cherry-pick the side track onto the main track, run `python -m pytest tests -q`, then Task 7.

---

### Task 1: Local HA sandbox harness

**Files:**
- Create: `tests/requirements.txt`, `tests/ha_sandbox.py`, `tests/test_ha_sandbox.py`
- Modify: `.gitignore` (add `.pytest_cache/` and `.venv/`)

**Interfaces:**
- Produces:
  - `FakeState(state: str, attributes: dict | None = None)`
  - `run_script(path: str, states: dict[str, FakeState], data: dict | None = None, now: datetime | None = None) -> SandboxResult`
  - `SandboxResult`: `service_calls: list[tuple[str, str, dict, bool]]` (domain, service, data, blocking); `errors: list[str]` (messages the script logged with `logger.error` — nothing else); `exception: BaseException | None` (an exception raised by the script; HA would swallow and log it); `compile_errors: list[str]`; `output: dict`; `elapsed: float` (seconds).
  - `now` defaults to `2026-11-20 13:30` Europe/Stockholm and drives the fake `dt_util`.

- [ ] **Step 1: Environment and version.** Create `.venv` (`python -m venv .venv`) and use it for all test runs. Read the installed Core version live (`GET /api/config`), fetch `homeassistant/components/python_script/manifest.json` and `helpers.py` at that tag from `raw.githubusercontent.com/home-assistant/core/<tag>/…`. Write `tests/requirements.txt` with `pytest` and `RestrictedPython==<manifest version>` (8.5 for 2026.11.2); install it into `.venv`.

- [ ] **Step 2: Write the failing tests** in `tests/test_ha_sandbox.py` (scripts written to `tmp_path`):
  - `test_runs_plain_script`: `hass.services.call("input_text", "set_value", {"entity_id": "input_text.x", "value": "v"}, True)` → `service_calls == [("input_text", "set_value", {"entity_id": "input_text.x", "value": "v"}, True)]`, `exception is None`.
  - `test_rejects_subscript_augassign`: `d = {"a": 1}` / `d["a"] += 1` → `compile_errors` non-empty.
  - `test_rejects_import`, `test_rejects_star_args` (`f(*[1])`), `test_rejects_range_1000` (`range(1000)`) → `compile_errors` non-empty or `exception is not None`.
  - `test_rejects_disallowed_dt_util`: `dt_util.set_default_time_zone` → `exception is not None`.
  - `test_reads_state_and_now`: `output["s"] = hass.states.get("sensor.a").state`, `output["h"] = dt_util.now().hour` → `output == {"s": "1.5", "h": 13}`.
  - `test_dt_util_semantics`: `dt_util.parse_datetime("garbage") is None`; `dt_util.as_local` of a naive datetime treats it as local time; `dt_util.as_local` of a UTC datetime converts to Europe/Stockholm; `dt_util.start_of_local_day()` is local midnight of `now`.
  - `test_logger_error_captured`: `logger.error("boom")` → `errors == ["boom"]`.
  - `test_exception_captured`: `float("x")` → `exception` is a `ValueError`, `errors == []`.

- [ ] **Step 3: Run** `python -m pytest tests/test_ha_sandbox.py -q` — expected: fails (module missing).

- [ ] **Step 4: Implement `tests/ha_sandbox.py`.** Copy from the tag's `helpers.py`, with a comment naming the tag: the allowlists (`ALLOWED_HASS`, `ALLOWED_EVENTBUS`, `ALLOWED_STATEMACHINE`, `ALLOWED_SERVICEREGISTRY`, `ALLOWED_TIME`, `ALLOWED_DATETIME`, `ALLOWED_DT_UTIL`), `IOPERATOR_TO_OPERATOR`, `guarded_import`, `guarded_inplacevar`, `StubPrinter`, `TimeWrapper`, and the body of `execute()` — `compile_restricted_exec`, the builtins (`safe_builtins` + `utility_builtins` + `limited_builtins` + `extra_builtins`), `protected_getattr` including the `async_` prefix rule, and the restricted globals (`_print_`, `_getattr_`, `_write_`, `_getiter_`, `_getitem_`, unpack guards, `_inplacevar_`, `hass`, `data`, `logger`, `output`). Replace HA objects with fakes: `FakeHass` (`.states.get/set/entity_ids/all/is_state/is_state_attr/remove`, `.services.call(domain, service, data=None, blocking=False)` recording calls, `.services.has_service`, `.bus.fire` no-op) and a `FakeDtUtil` object exposing the ten allowed names with HA's semantics on `ZoneInfo("Europe/Stockholm")` (see `test_dt_util_semantics`). The script's `logger` is a stub that appends `logger.error` messages to `errors` and ignores other levels.

- [ ] **Step 5: Run** `python -m pytest tests/test_ha_sandbox.py -q` — expected: all pass.

- [ ] **Step 6: Commit** `test: add a local mirror of the HA python_script sandbox`.

---

### Task 2: Planner inputs, budget and slot writing

**Files:**
- Create: `python_scripts/heating_plan.py`, `tests/test_heating_plan.py`, `tests/fixtures/prices_2026-11-19.json`

**Interfaces:**
- Consumes: `run_script`, `FakeState`, `SandboxResult` (Task 1).
- Produces:
  - Service `python_script.heating_plan`, data `{"forecast": [{"datetime": "<UTC ISO string>", "temperature": <float>}, …]}`. A missing or non-list `forecast` counts as no forecast.
  - Reads `sensor.nordpool_kwh_se3_sek_3_095_0` (`raw_tomorrow`), `sensor.tvattstugan_p10_24h`, `sensor.koket_p10_24h`, `input_number.heating_block_cold|chilly|mild|warm`, `input_number.heating_budget_factor`, `input_number.heating_laundry_full_p10`, `input_number.heating_kitchen_floor_p10`, `input_text.heating_plan_a`, `input_text.heating_plan_b`.
  - Writes exactly one call `("input_text", "set_value", {"entity_id": <slot>, "value": <plan string>}, True)` or none.
  - `optimise(excess: list, m: int, b: int, first_free: int) -> list` inside the script: `excess` = the 96 shifted excess values, `m` and `b` in **quarters**, returns `[[start, end], …]` quarter indices with `end` exclusive. In this task it is a stub returning `[]`.
  - Test helpers in `tests/test_heating_plan.py`: `make_states(prices=None, laundry="22.5", kitchen="22.0", helpers=None, slot_a="", slot_b="") -> dict`, `make_forecast(temps: list, start_utc="2026-11-20T23:00:00+00:00") -> list`, `parse_plan(value) -> (date, blocks, info)`, `run(states, forecast, now=None) -> SandboxResult` (runs `python_scripts/heating_plan.py`).

- [ ] **Step 1: Create the fixture** `tests/fixtures/prices_2026-11-19.json`: 96 entries `{"start", "end", "value"}` dated 2026-11-21 (tomorrow relative to the default `now`), local ISO with offset, 15-minute slots, values in order (spot SEK/kWh captured for 2026-11-19):
  `1.395, 1.406, 1.411, 1.421, 1.385, 1.398, 1.424, 1.437, 1.395, 1.423, 1.435, 1.462, 1.386, 1.434, 1.466, 1.539, 1.466, 1.489, 1.529, 1.639, 1.502, 1.68, 1.765, 1.946, 1.797, 1.852, 2.242, 2.624, 2.147, 2.403, 2.52, 2.596, 2.804, 2.848, 2.877, 2.964, 2.678, 2.783, 2.78, 2.818, 2.784, 2.78, 2.898, 2.884, 2.79, 2.777, 2.695, 2.639, 2.722, 2.548, 2.524, 2.54, 2.567, 2.579, 2.65, 2.606, 2.649, 2.734, 2.541, 2.542, 2.528, 2.57, 2.646, 2.82, 2.667, 2.494, 2.496, 2.45, 2.684, 2.463, 2.38, 2.384, 2.761, 2.437, 2.401, 2.33, 2.581, 2.272, 2.191, 2.118, 2.131, 2.069, 1.773, 1.687, 1.806, 1.767, 1.73, 1.674, 1.728, 1.606, 1.528, 1.434, 1.503, 1.456, 1.395, 1.306`.
  `make_states` converts `start`/`end` to aware `datetime` objects, as in the state machine.

- [ ] **Step 2: Write the failing tests.** Default `now` 2026-11-20 13:30, tomorrow 2026-11-21. Every test also asserts `exception is None`. Assert date and info only (blocks come in Task 3).
  - `test_budget_at_anchor`: 24 × −2.5 → `t=-2.5, c=1.00, m=3.00, b=6.00`.
  - `test_budget_between_anchors`: 24 × 0.0 → `m=3.50, b=7.00`.
  - `test_budget_outside_anchors`: 24 × −10.0 → `m=1.00, b=2.00`; 24 × 10.0 → `m=6.00, b=12.00`.
  - `test_coldest_six_hours`: 18 × 3.0 and 6 × −7.0 → `t=-7.0, m=1.00, b=2.25`.
  - `test_laundry_correction` (−2.5 day): laundry `21.5` → `c=0.50, m=1.50, b=3.00`; `21.0` → `c=0.00, m=0.00, b=0.00`; `22.0` → `c=1.00`; `21.2` → `c=0.20, m=0.50, b=1.00` and no blocks.
  - `test_kitchen_floor`: kitchen `20.9` → `c=0.00`; `21.0` → `c=1.00`.
  - `test_quarter_rounding_epsilon`: block_chilly `2.5`, laundry `21.9` (c 0.9, 2.5 × 0.9 = 2.25) → `m=2.25`.
  - `test_helper_defaults`: factor `0`, `unknown`, `abc`, missing entity → 2.0; thresholds `0` → 22.0 / 21.0; anchor `0` (chilly) at −2.5 → `m=0.00`; anchor `unavailable` → 3. (Review Focus 3.)
  - `test_missing_inputs_write_nothing`: 17 forecast entries inside tomorrow; `forecast` key absent; `forecast` a string; laundry `unavailable`; kitchen `unknown`; kitchen `abc`; no `raw_tomorrow`; a gap between two price slots; a `None` value → `service_calls == []` and `errors` non-empty in each case.
  - `test_prices_for_wrong_day`: `raw_tomorrow` dated 2026-11-20 → no call, `errors` non-empty. (Review Focus 5.)
  - `test_forecast_window`: 58 hourly entries from today 14:00 local; tomorrow's 24 at −2.5, all others at −20 → `t=-2.5`. (Review Focus 2.)
  - `test_utc_price_datetimes`: fixture with `start`/`end` as UTC-aware datetimes, and as ISO strings → the same plan string as local datetimes. (Review Focus 1.)
  - `test_hourly_price_slots`: 24 one-hour slots → accepted (expanded to 96 quarters).
  - `test_dst_day_empty_plan`: `now` 2027-03-27 13:30 with 92 contiguous quarters for 2027-03-28 → `2027-03-28 |t=na;l=na;k=na;c=na;m=0.00;b=0.00`; `now` 2027-10-30 13:30 with 100 contiguous quarters → the same form for 2027-10-31. Coverage of local 00:00–24:00 is checked before the count, so 95 entries with a gap is an error, not a DST day.
  - `test_slot_choice`: both `""` → A; A `unknown` → A; A dated today → B; A dated yesterday, B dated today → A; A or B dated tomorrow → no call and `errors == []`.
  - `test_write_is_blocking`: the call's fourth element is `True`.

- [ ] **Step 3: Run** `.venv` `python -m pytest tests/test_heating_plan.py -q` — expected: fails.

- [ ] **Step 4: Implement `python_scripts/heating_plan.py`** following spec steps 1–7 in that order, with the `optimise` stub. RestrictedPython rules (verified under 8.5): no `d[k] += x`, no tuple `+=`, no `f(*args)`, no names starting with `_`, no `import`, no `dict()`, `map`, `filter`, `reversed`, `type()` or `class`; `range` below 1000 elements. Parse string times with `dt_util.parse_datetime` (returns `None` on garbage), then `dt_util.as_local`. Log every stop reason except "already planned" with `logger.error`. Format with `"%.2f" % x` (`"%.1f"` for `t`).

- [ ] **Step 5: Run** `python -m pytest tests -q` — expected: all pass.

- [ ] **Step 6: Commit** `feat: add the heat pump plan script inputs and budget`.

---

### Task 3: Block optimisation and midnight carry-over

**Files:**
- Modify: `python_scripts/heating_plan.py`, `tests/test_heating_plan.py`

**Interfaces:**
- Consumes: Task 2's script, `optimise` signature and test helpers.
- Produces: the real `optimise(excess, m, b, first_free)`.

- [ ] **Step 1: Write the failing tests** (each also asserts `exception is None`):
  - `test_thursday_one_block`: fixture, −2.5 day, factor `1.0` → `08:00-11:00`.
  - `test_thursday_default_budget`: fixture, −2.5 day → `08:00-11:00,13:15-16:15`.
  - `test_thursday_short_blocks`: block_chilly `1` → `08:00-09:00,10:15-11:15`.
  - `test_thursday_long_blocks`: forecast 24 × 7.5 (m 6 h, b 12 h) → `07:30-11:30,13:30-19:30`.
  - `test_block_rules`: for each plan above: every block ≥ 1 h and ≤ m; gap after a block of L quarters ≥ `max(4, ceil(L/2))` quarters; total ≤ b; each block's mean price − day mean > 0.10.
  - `test_flat_day_no_blocks`: 96 × 1.0 → no blocks; 92 × 1.0 then 4 × 1.05 → no blocks.
  - `test_only_the_expensive_part`: 0.50 all day, 00:00–02:00 at −0.2, 17:00–18:00 at 1.5, −2.5 day → exactly `17:00-18:00`.
  - `test_tie_is_deterministic`: 1.0 all day, 08:00–09:00 and 16:00–17:00 at 2.0, block_chilly `1`, factor `1.0`, −2.5 day → `08:00-09:00` on repeated runs.
  - `test_midnight_gap_carried`: 3.0 at 00:00–03:00, 1.0 otherwise, −2.5 day; slot dated today `2026-11-20 21:00-24:00|…` → `01:30-03:00`; `2026-11-20 22:30-23:30|…` → `00:30-03:00`; slot dated `2026-11-19` (stale) → `00:00-03:00`.
  - `test_garbage_slots`: A `hello`, B `2026-11-20 xx|yy` → no exception, plan written to A, carry-over none (`00:00-03:00` with the midnight prices). (Review Focus 4.)
  - `test_worst_case_runtime`: block_warm `8`, factor `3`, forecast 24 × 10 → `elapsed < 0.5`.

- [ ] **Step 2: Run** `python -m pytest tests/test_heating_plan.py -q` — expected: the new tests fail.

- [ ] **Step 3: Implement `optimise`** exactly as the spec's Optimisation section: prefix sums of `excess`; backward table `g[i][u]` (lists of lists) with the leave and block transitions, a block only when its sum `> 1e-9`; forward reconstruction from `first_free` taking, at each free quarter, the shortest `L` whose value equals `g[i][u]` within 1e-9, else leaving the quarter. Quarters before `first_free` are never blocked. `first_free = max(0, end + gap(L) − 96)` from the last block of the slot dated today (end `24:00` = 96), else 0.

- [ ] **Step 4: Run** `python -m pytest tests -q` — expected: all pass.

- [ ] **Step 5: Commit** `feat: place heat pump blocks with an interval DP`.

---

### Task 4 (side track): Heating package and its template test

**Files:**
- Create: `packages/heating.yaml`, `tests/test_templates.py`
- Modify: `tests/requirements.txt` (append `jinja2`; create the file with `pytest` and `jinja2` if Task 1 is not on this track), `CLAUDE.md` (the `packages/` row: "Bundled component configs (engineheater, heating)")

**Interfaces:**
- Produces: the ten helpers of the spec's helper table (exact keys and ranges; `step` 0.25 for hours, 0.1 for factor and °C; `mode: box`), `sensor.tvattstugan_p10_24h`, `sensor.koket_p10_24h`, `binary_sensor.varmepump_blockerad_enligt_plan`.
- Produces: `tests/test_templates.py` helper `render(template: str, states: dict, now: datetime) -> str` with jinja2 and stubs for `states()`, `is_state()`, `now()`, `timedelta`, `float` with default — reused by Task 6.

- [ ] **Step 1: Write the failing tests** in `tests/test_templates.py`, loading the binary sensor's `state` template from `packages/heating.yaml` (now 2026-11-20 13:30, master switch `on` unless stated):
  - slot A `2026-11-20 13:00-14:00|…` → `True`; `2026-11-20 12:00-13:30|…` → `False` (end exclusive); `2026-11-20 13:30-24:00|…` → `True`; at 23:59 with `22:00-24:00` → `True`.
  - empty block list `2026-11-20 |…` → `False`; slot dated yesterday or tomorrow → `False`; `unknown`, `""`, `hello` → `False`; `2026-11-20 xx,13:00-14:00|…` → `True` (malformed piece skipped).
  - plan in slot B, A dated tomorrow → uses B.
  - master switch `off` → `False`.

- [ ] **Step 2: Run** `python -m pytest tests/test_templates.py -q` — expected: fails.

- [ ] **Step 3: Write the package.** Keys: `input_boolean:`, `input_number:`, `input_text:` (both slots `max: 255`, no `initial`), `sensor:` (two `platform: statistics`: `name: "Tvättstugan p10 24h"` / `unique_id: tvattstugan_p10_24h` on `sensor.felix_rum_temperature`; `name: "Köket p10 24h"` / `unique_id: koket_p10_24h` on `sensor.xiaomi_lys3_temperatur`; `state_characteristic: percentile`, `percentile: 10`, `max_age: {hours: 24}`), `template:` (binary sensor `name: "Värmepump, blockerad enligt plan"`, `unique_id: varmepump_blockerad_enligt_plan`). UI names: Värmeplan aktiv; Max block vid −7,5° / −2,5° / +2,5° / +7,5°; Budgetfaktor; Tvättstuga p10 full budget; Kök p10 golv; Värmeplan A; Värmeplan B.
  Binary sensor state: off unless `input_boolean.heating_plan_enabled` is on; use whichever slot starts with `now().strftime('%Y-%m-%d') ~ ' '`; take the text between the first space and `|`, split on `,`; on if any piece of the form `HH:MM-HH:MM` satisfies `start <= now().strftime('%H:%M') < end` as strings.

- [ ] **Step 4: Run** `python -m pytest tests/test_templates.py -q` and `python -c "import yaml; yaml.safe_load(open('packages/heating.yaml', encoding='utf-8'))"` — expected: pass, no error.

- [ ] **Step 5: Commit** `feat: add the heating package with plan helpers and sensors`.

### Task 5 (side track): Automations

**Files:**
- Modify: `automations.yaml` (append two automations; delete the whole entry with `id: '1695920348544'`)

**Interfaces:**
- Consumes: entity ids from Task 4; `python_script.heating_plan` and its `forecast` key (Task 2 Interfaces).

- [ ] **Step 1: Add `Värmepumpen, planera morgondagen`** (`id: '1795400000001'`, `mode: single`): triggers `binary_sensor.template_nordpool_tomorrow_valid` to `on`, and `time_pattern` `minutes: "/30"`. Condition template: `tomorrow_valid` is `on` and neither slot starts with `(now() + timedelta(days=1)).strftime('%Y-%m-%d')`. Actions: `weather.get_forecasts` on `weather.smhi_home`, `type: hourly`, `response_variable: fc`, `continue_on_error: true`; then `python_script.heating_plan` with `forecast: "{{ fc['weather.smhi_home'].forecast if fc is defined and 'weather.smhi_home' in fc else [] }}"`.
- [ ] **Step 2: Add `Värmepumpen, följ plan`** (`id: '1795400000002'`, `mode: restart`): triggers state change of `binary_sensor.varmepump_blockerad_enligt_plan`; `switch.varmepumpen_a` `from: unavailable`; `homeassistant` start; `time_pattern` `minutes: "/15"`. Condition template: `states('switch.varmepumpen_a') in ['on', 'off']` and `is_state('binary_sensor.varmepump_blockerad_enligt_plan', 'on') != is_state('switch.varmepumpen_a', 'on')`. Action: `if` the plan sensor is currently `on` → `switch.turn_on`, else `switch.turn_off`, target `switch.varmepumpen_a`.
- [ ] **Step 3: Delete `Värmepumpen, styrning`** (the entire list item with `id: '1695920348544'`). Leave `1662395114345` and `1662395326862` untouched.
- [ ] **Step 4: Verify**: parse with a YAML loader that tolerates `!secret`/`!include`; assert ids unique, `1695920348544` absent, both new ids present.
- [ ] **Step 5: Commit** `feat: plan and follow heat pump blocks, drop the p75 automation`.

### Task 6 (side track): Dashboard card

**Files:**
- Modify: `lovelace_manual.yaml` (Huset view, directly after the entities card titled `Stäng av` that lists `switch.varmepumpen_a`), `tests/test_templates.py`

**Interfaces:**
- Consumes: entity ids and `render()` from Task 4; the plan string grammar (Global Constraints).

- [ ] **Step 1: Write the failing tests** in `tests/test_templates.py`, loading the card's `content` from `lovelace_manual.yaml`: slot A today `08:00-11:00`, B tomorrow → output contains `Idag`, `08:00-11:00`, `Imorgon`; no slot dated tomorrow at 16:00 → contains `Ingen plan för imorgon`; at 12:00 → does not; no slot dated today → `Ingen plan för idag`; empty block list → `Inga block`; DST info `na` → shows `–`, no exception.
- [ ] **Step 2: Add a markdown card** titled `Värmeplan`: for `Idag` and `Imorgon`, the slot starting with that date; its blocks (or `Inga block`) and the line `Kallaste 6 h: {t}° · Tvättstuga p10 {l}° · Kök p10 {k}° · Justering {c×100} % · Max block {m} h · Budget {b} h` (`na` shown as `–`). After 15:00 with no slot dated tomorrow: `Ingen plan för imorgon`. No slot dated today: `Ingen plan för idag`.
- [ ] **Step 3: Add an entities card** titled `Värmeplan, inställningar`: the master switch, the seven `input_number` helpers, both p10 sensors.
- [ ] **Step 4: Run** `python -m pytest tests/test_templates.py -q` and parse `lovelace_manual.yaml` — expected: pass.
- [ ] **Step 5: Commit** `feat: show the heat pump plan on the Huset dashboard`.

---

### Task 7: Deploy and verify live

**Files:** none new (merge only).

**Interfaces:**
- Consumes: everything above, cherry-picked onto the main track with all tests passing.

- [ ] **Step 1: Stop and ask Rickard** for the go-ahead to squash, merge to master, push and pull to live. Do nothing below without it.
- [ ] **Step 2: Pre-checks.** `ssh -o BatchMode=yes hassio.nord.cc 'cd /config && git status --short'` — dirty files mean UI edits: sync them first (palace recipe `wing_hass/patterns`). Read the live dashboard (`lovelace/config`, `url_path: null`) and compare with `lovelace_manual.yaml` on master; sync first if it differs. Record the state of `switch.varmepumpen_a`.
- [ ] **Step 3: Merge, push, pull** per the recipe; `POST /api/config/core/check_config` → `valid`.
- [ ] **Step 4: Reload in this order:** `input_boolean`, `input_number`, `input_text`; set every helper to its built-in default (master switch stays **off**); then `statistics`, `template`, `python_script`; then `automation` last. If entities do not appear, ask Rickard before restarting HA.
- [ ] **Step 5: Safety check.** Both new automations exist and are `on`; `automation.varmepumpen_styrning` is gone (remove an orphaned registry entry with `config/entity_registry/remove`). With the master switch off the plan sensor is `off`, so if `switch.varmepumpen_a` is `on`, trigger `Värmepumpen, följ plan` and confirm it turns `off` within a minute. If anything here fails, roll back: `switch.turn_off` `switch.varmepumpen_a`, revert the merge commit, push, pull, reload `automation` — and report.
- [ ] **Step 6: Check the binary sensor live** with `POST /api/template`, using the deployed template with the slot states replaced by literals: block covering now → `on`; block ended → `off`; slot dated yesterday → `off`. No real block is triggered.
- [ ] **Step 7: Plan for tomorrow.** Requires `tomorrow_valid` on (normally after 13:00–14:00; before that, wait). If a slot is dated tomorrow from before Step 4, clear it. `automation.trigger` on `Värmepumpen, planera morgondagen` (conditions kept); expect one slot dated tomorrow with a plausible plan against tomorrow's prices. Read the run's trace (`trace/get`) and report the `python_script` step duration; above 5 seconds, report it as a problem.
- [ ] **Step 8: Turn on** `input_boolean.heating_plan_enabled`.
- [ ] **Step 9: Deploy the dashboard** with `lovelace/config/save`, read it back for equality, and confirm the card renders both plans (`POST /api/template` with the card content).
- [ ] **Step 10: Categories**: `config/category_registry/list` for scopes `automation` and `helpers`, create `Heating` where missing, assign via `config/entity_registry/update` to the two automations and the ten helpers; report any entity that cannot take it.
- [ ] **Step 11: Report to Rickard**: tomorrow's plan, the step duration, and his check for the next day (about 5 minutes: heating blocked at the planned times; `Värmepumpen, styrning` gone).
