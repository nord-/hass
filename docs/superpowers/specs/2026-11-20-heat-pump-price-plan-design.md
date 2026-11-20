# Heat pump price plan — design

Date: 2026-11-20
Status: draft, revised after two independent reviews, awaiting Rickard's review

## Problem

`Värmepumpen, styrning` (automation id `1695920348544`) blocks the IVT heat pump (`switch.varmepumpen_a`, a Shelly 1; on = space heating **and** hot water production blocked) whenever `binary_sensor.template_nordpool_price_not_high` is off, i.e. whenever the current price is above the 75th percentile of today (plus tomorrow once known) and above the 3-day average. There is no limit on how long a block lasts and no temperature guard (the indoor conditions are disabled).

On days with high prices for most of the day this blocks the heating for far too long. On Thursday 2026-11-19 heating was blocked 08:00–19:15 except for about an hour, at about −2 °C outdoors; the afternoon block alone ran 5.5 h because the 75th percentile dropped from 3.88 to 3.49 kr when Friday's cheaper prices arrived at 13:12 and the whole afternoon suddenly counted as "expensive". The kitchen fell from 22.2 to 21.4 °C. In addition, quarter-hour prices make the switch flap in 15-minute steps.

## Goal

Avoid the most expensive periods without making the house cold. Success means:

- No block longer than the temperature-dependent maximum, a bounded total per calendar day, and a recovery gap after every block that grows with the block.
- Blocks land where the price is furthest above the day's mean, judged over the whole block, so one expensive quarter cannot drag three cheap ones into a block, and nothing is blocked on a day where no block is clearly above the mean.
- The plan for a day is fixed once made; it does not move when the price window slides.
- When data is missing, heating is not blocked (warm and slightly more expensive beats cold).

## Decisions

| Topic | Decision |
|---|---|
| When to plan | Once per day, for tomorrow 00:00–24:00, as soon as tomorrow's Nordpool prices arrive (normally 13:00–14:00), retried every 30 minutes until a plan exists. The existing 15:00 guard (`Nordpool - reload prices`) stays. |
| Plan stability | A plan, once written, is never recomputed for the same date. A plan is only written when all inputs are present. To force a re-plan, clear the slot by hand. |
| Indoor feedback during the day | None. The house reacts with up to a day's delay; the master switch is the only override. |
| Outdoor temperature | Mean of the **6 coldest hours** of the SMHI hourly forecast (`weather.smhi_home`, `weather.get_forecasts`, `type: hourly`) within tomorrow 00:00–24:00, requiring at least 18 hourly entries inside tomorrow. The coldest hours tend to coincide with the morning price peak. No fallback: `sensor.template_home_temp` reads 98 °C when its sensors are dead (`float(98)` default) and reflects 13:00, not tomorrow. |
| Max block length | Interpolated linearly between anchors, flat outside them: −7.5 °C → 1 h, −2.5 °C → 3 h, +2.5 °C → 4 h, +7.5 °C → 6 h. |
| Daily budget | Budget factor × max block length (factor 2.0). The budget is a ceiling, not a target. Each calendar day has its own budget; blocks late today do not count against tomorrow (accepted: a costly evening followed by a costly night can block about 12 h in 16.5 h at −2.5 °C). |
| Indoor correction | Based on the 10th percentile of the last 24 h, read at planning time. Laundry room (`sensor.felix_rum_temperature`, misnamed): full budget at p10 ≥ 22.0 °C, minus 10 % per 0.1 °C below, 0 at 21.0 °C. Kitchen (`sensor.xiaomi_lys3_temperatur`): floor 21.0 °C — p10 below the floor gives budget 0. The 1.5–2.5 day lag and the steep slope are accepted. |
| Block rules | Minimum block 1 h; maximum block = corrected max block length; after a block of length L the heating runs for at least max(1 h, L / 2) before the next block, also across midnight; total ≤ budget; a block is only chosen if its mean price is more than 0.10 SEK/kWh (spot) above tomorrow's mean. |
| Placement | Exact optimisation maximising the summed shifted excess, price − tomorrow's mean − 0.10, over blocked quarters. A quarter therefore only adds value if it is more than 0.10 above the mean, so a block does not grow into quarters at roughly the normal price just because its average still holds (Rickard, 2026-11-20: block only the expensive part; a 1.50 kr hour on a 0.50 kr day gives 17:00–18:00, not 17:00–20:00). A block may still contain cheaper quarters where that is needed to reach 1 h. Measuring against the recovery gap's price instead was considered and rejected: the house is slow, so recovery spreads over more than the gap. |
| Runtime | `python_script` (exact optimisation needs real loops; Jinja cannot do it on the Pi). |
| Visibility | Dashboard only, no notifications. A missing plan shows on the dashboard card. |
| Organisation | Every new helper and automation gets the HA category **Heating**. Everything is checked into git; helpers are defined in YAML because `.storage` is git-ignored. |
| Old automation | `Värmepumpen, styrning` is deleted from `automations.yaml` (git keeps the history). A UI-disabled state lives only in `.storage` and could silently come back. |
| Immersion heater | `switch.varmepumpen_b` blocks the immersion heater and keeps its current logic unchanged: `Värmepumpen, blockera elpatron` (id `1662395326862`) and `Värmepumpen, tillåt elpatron` (id `1662395114345`). It must never run when the price is above p75. |
| Hot water | Because `switch.varmepumpen_a` also blocks hot water production, a block pauses both. Accepted; the tank buffers it. |
| Hardware failsafe | None. If HA or the Pi dies during a block, the Shelly stays on until HA is back. Accepted. |

## Components

### `packages/heating.yaml` (new)

Helpers (entity ids come from the keys; UI names are Swedish):

| Entity | Purpose | Range | Built-in default |
|---|---|---|---|
| `input_boolean.heating_plan_enabled` | Master switch. Off = never block. | — | — |
| `input_number.heating_block_cold` | Max block at −7.5 °C (h) | 0–6 | 1 |
| `input_number.heating_block_chilly` | Max block at −2.5 °C (h) | 0–6 | 3 |
| `input_number.heating_block_mild` | Max block at +2.5 °C (h) | 0–8 | 4 |
| `input_number.heating_block_warm` | Max block at +7.5 °C (h) | 0–8 | 6 |
| `input_number.heating_budget_factor` | Daily budget = factor × max block; 0 = use default | 0–3 | 2.0 |
| `input_number.heating_laundry_full_p10` | Laundry p10 for full budget (°C); 0 = use default | 0–25 | 22.0 |
| `input_number.heating_kitchen_floor_p10` | Kitchen p10 floor (°C); 0 = use default | 0–25 | 21.0 |
| `input_text.heating_plan_a` | Plan slot A | max 255 | — |
| `input_text.heating_plan_b` | Plan slot B | max 255 | — |

None of the helpers has `initial`, so values changed from the dashboard survive restarts. A helper without a restored value starts at its `min` (HA behaviour), not `unknown`. The ranges are chosen so that this is safe: the factor and the two thresholds have `min: 0`, and the script treats 0 as "use the built-in default"; the four anchors at 0 mean "no blocking at that temperature", so a fully lost restore state gives no blocks, which the dashboard card shows. The master switch starts off without a restored value: no blocking. Deployment sets every helper to its built-in default once.

Sensors:

- Two `statistics` sensors with `name` and matching `unique_id`, `state_characteristic: percentile`, `percentile: 10`, `max_age: {hours: 24}` (the mapping form used in `sensors.yaml`), no `sampling_size` (the buffer is then bounded by `max_age` only): "Tvättstugan p10 24h" → `sensor.tvattstugan_p10_24h`, "Köket p10 24h" → `sensor.koket_p10_24h`. The percentile is sample-based, not time-weighted; accepted.
- Template binary sensor "Värmepump, blockerad enligt plan" → `binary_sensor.varmepump_blockerad_enligt_plan` (`unique_id: varmepump_blockerad_enligt_plan`): on when `input_boolean.heating_plan_enabled` is on, one of the two plan slots carries today's date, and the current local time as `HH:MM` lies inside one of that slot's blocks, compared as strings (`start <= now < end`, so `24:00` works without `today_at`). Any parse problem, or no slot dated today, gives off.

### Plan slots and format

Two slots instead of "today" and "tomorrow" helpers, so no midnight copy is needed: the binary sensor uses the slot dated today, and the planner writes tomorrow's plan to slot A unless A is dated today, otherwise to slot B.

```
<date> <blocks>|<info>
2026-11-21 08:00-11:00,15:30-16:30|t=-1.8;l=22.10;k=21.43;c=1.00;m=3.00;b=6.25
```

- `<blocks>` is a comma-separated list of `HH:MM-HH:MM`, local time; the end of the day is written `24:00`. A day with no blocks is written with the date and an empty block list (`2026-11-21 |…`), so "planned, nothing to block" is distinguishable from "not planned".
- `<info>` carries what the dashboard shows: the coldest-6-hours mean (`t`), laundry and kitchen p10 (`l`, `k`), correction factor (`c`), max block and budget in hours after correction (`m`, `b`). The blocks may total less than `b`, since the budget is a ceiling.
- The longest possible plan (12 one-hour blocks) plus info is about 210 characters, under the 255 limit.

### `python_scripts/heating_plan.py` (new)

Called as `python_script.heating_plan` with `forecast` (the hourly forecast list from `weather.get_forecasts`, or an empty list) in its data. Everything else it reads from states itself:

- Prices: `raw_tomorrow` of `sensor.nordpool_kwh_se3_sek_3_095_0` (entries with `start`, `end`, `value`). In the state machine `start`/`end` are `datetime` objects; over REST they appear as ISO strings. The script accepts both. The raw spot price is enough: fees are a constant per kWh and VAT a constant factor, so with the excess-over-mean objective they only scale the objective and do not change the choice.
- Helpers, both p10 sensors, and both plan slots.

Steps:

1. Tomorrow = today + 1 day (local). If a slot already carries tomorrow's date, stop (idempotent).
2. Validate the prices: entries contiguous from tomorrow 00:00 to 24:00 local, no missing values, slot length taken from `start`/`end` (15 or 60 min; 60-min slots are expanded to four quarters). Otherwise log an error and stop without writing. If the day does not have exactly 96 quarters (DST change), write an empty plan for it.
3. Outdoor temperature: the forecast entries inside tomorrow (`datetime` is a UTC string; convert with `dt_util.parse_datetime` and `dt_util.as_local`). Fewer than 18 entries: log an error and stop without writing. Otherwise `t` = mean of the 6 lowest temperatures.
4. Either p10 sensor `unavailable`, `unknown` or not a number: log an error and stop without writing.
5. `base` = max block from the anchors at `t`. Correction `c = min(c_laundry, c_kitchen)`, with `c_laundry = clamp(1 − (full_p10 − p10_laundry) / 1.0, 0, 1)` and `c_kitchen = 0 if p10_kitchen < floor else 1`.
6. `m = floor_quarter(base × c)`, `b = floor_quarter(factor × base × c)` (both computed from `base`, rounded down to whole quarters). If `m < 1 h`, there are no blocks.
7. Optimise (below) and write the plan with `hass.services.call("input_text", "set_value", {...}, True)` (blocking, so the state is set before the script returns; `hass.states.set` would not change the helper's own value).

All errors are logged at `error` level, because `configuration.yaml` sets `logger: default: error` and lower levels are dropped. HA swallows exceptions from a `python_script`; a failed run simply leaves no plan, which the next 30-minute retry and the dashboard card cover.

Fixed constants in the script (not helpers): minimum block 1 h, gap rule max(1 h, L / 2), minimum block excess 0.10 SEK/kWh, slope 10 % per 0.1 °C, anchor temperatures −7.5 / −2.5 / +2.5 / +7.5 °C, the 6 coldest hours, the minimum of 18 forecast entries, and the built-in helper defaults.

The script is written for RestrictedPython: no augmented assignment to subscripts or attributes (`d[k] += x`), no names starting with `_`, no `import`, no `dict()`, `map`, `filter` or `reversed`, `range` below 1000 elements, and only the builtins and `dt_util` functions HA exposes.

#### Optimisation

Interval dynamic programming over tomorrow's 96 quarters with prefix sums of the shifted excess `e[q] = price[q] − mean − 0.10`. Computed backwards: `g[i][u]` is the best total shifted excess obtainable from quarter `i` to the end of the day when quarter `i` is free to start a block and `u` quarters of budget are already spent; `g[96][u] = 0`. From quarter `i`: either leave it unblocked (`g[i+1][u]`), or place a block of length `L` (from 1 h to `m`, in quarters, `u + L ≤ b`, ending by quarter 96, block sum `sum(e[i..i+L)) > 0`) worth that sum plus `g[min(i + L + gap(L), 96)][u + L]`. The plan is reconstructed forwards from `first_free` with `u = 0`: at each free quarter take the shortest `L` whose value equals `g[i][u]` within 1e-9, otherwise leave the quarter. This makes ties deterministic: the earliest start wins, then the shortest block. About 97 × 97 × 29 ≈ 270 000 steps at the helper maxima (8 h, factor 3), far fewer in practice.

#### Midnight boundary

The planner reads the slot dated today (the day before tomorrow); a slot with any other date counts as no plan. Only the gap is carried over: if today's last block ended at `e` with length `L`, tomorrow's first free quarter is `e + gap(L) − 24:00` when that is after 00:00. A block cannot continue across midnight; a block ending at 24:00 is treated like any other. No plan for today: tomorrow starts free.

### `automations.yaml`

| Automation | Triggers | Condition | Action |
|---|---|---|---|
| `Värmepumpen, planera morgondagen` (new) | `binary_sensor.template_nordpool_tomorrow_valid` → on; every 30 min | `tomorrow_valid` is on and no plan slot carries tomorrow's date | `weather.get_forecasts` (hourly, `continue_on_error: true`); `python_script.heating_plan` with the forecast, guarded with `is defined` so a failed call passes an empty list |
| `Värmepumpen, följ plan` (new, `mode: restart`) | `binary_sensor.varmepump_blockerad_enligt_plan` changes; `switch.varmepumpen_a` leaves `unavailable`; HA start; every 15 min | `switch.varmepumpen_a` differs from the plan sensor's current state | Plan sensor on → `switch.turn_on`; otherwise `switch.turn_off`. The action reads the sensor's current state, not the trigger's. |
| `Värmepumpen, styrning` (existing) | — | — | Deleted |

Both new automations are created in `automations.yaml` with ids, so they stay editable in the UI. The 30-minute retry covers HA restarts, sensors that are not ready right after a restart, late prices and failed runs. Because of the 15-minute re-assertion, a manual toggle of `switch.varmepumpen_a` is undone within 15 minutes; the master switch is the override.

### `lovelace_manual.yaml`

A markdown card in the **Huset** view, after the existing `Värmepumpen` entities card, showing today's and tomorrow's plan (blocks, coldest-6-hours mean, both p10 values, correction, max block and budget). It picks the slots by date, not by name. After 15:00 with no slot dated tomorrow it shows "Ingen plan för imorgon". The helpers and the master switch go in an entities card next to it. The dashboard is deployed with `lovelace/config/save`; it was synced with live (commit `03f1f50`) before this work.

### Categories

After deploy, a category **Heating** is created in each scope it is needed (`automation` and `helpers`) where missing and assigned through the websocket API (`config/entity_registry/update`) to every new automation and helper the registry allows. The assignment itself lives in `.storage`, not git. The statistics and template sensors will most likely not show under Helpers; any entity the registry does not accept a category for is reported, not worked around.

## Error handling

| Situation | Behaviour |
|---|---|
| Tomorrow's prices never arrive | The 15:00 guard reloads and notifies (unchanged). No plan → no blocking tomorrow; the dashboard card shows it. |
| Prices incomplete or malformed | No plan written; retried every 30 minutes. |
| DST change (92 or 100 quarters) | Empty plan for that day. |
| SMHI call fails or too few forecast entries | No plan written; retried every 30 minutes. |
| A p10 sensor unavailable, unknown or non-numeric (e.g. just after a restart) | No plan written; retried every 30 minutes. |
| Script raises an exception | Logged by HA at error level; no plan; retried every 30 minutes. |
| `tomorrow_valid` flaps or the planner is triggered again | Skipped: a slot already carries tomorrow's date. |
| `switch.varmepumpen_a` toggled by hand, a command lost, or the Shelly reconnects | Re-asserted within 15 minutes, immediately when it leaves `unavailable`. |
| Helper restore state lost | Factor and thresholds fall back to built-in defaults; anchors at 0 give no blocks; master switch off gives no blocking. |
| First day after deploy | No plan for today → no blocking until the first planned day. |
| HA or the Pi dies during a block | The Shelly stays on (blocked) until HA is back. Accepted. |

Not included (YAGNI): re-planning during the day, indoor feedback during the day, a manual override beyond the master switch, notifications, a hardware failsafe.

## Testing

### Unit tests (pytest, `tests/test_heating_plan.py`, checked in)

The script is compiled with `RestrictedPython.compile_restricted_exec`, pinned to the RestrictedPython version that the installed HA Core ships (read the installed version live at implementation time and look it up in that tag's `python_script/manifest.json`; on 2026-11-20 that was Core 2026.11.2 with RestrictedPython 8.5), and run with globals that mirror that tag's `homeassistant/components/python_script/helpers.py` (the same builtins, guards and `dt_util` subset) and a fake `hass` that serves states and records service calls. That way a construct HA's sandbox rejects fails the test, not the live run. Price fixtures use timezone-aware `datetime` objects, as in the state machine.

1. Prices of 2026-11-19 as a fixture: with factor 1.0, 3 h max block (so a 3 h budget) the plan is `08:00-11:00`; with factor 2.0 (6 h budget) it is `08:00-11:00,13:15-16:15` (both checked with a prototype of this DP on the session's price history).
2. Budget curve: at each anchor, between anchors, outside them, rounding down to whole quarters; `m` and `b` both computed from `base`; `t` is the mean of the 6 coldest forecast hours.
3. Block rules: every block ≥ 1 h and ≤ `m`, gap after each block ≥ max(1 h, L / 2), total ≤ `b`, mean excess of every block > 0.10.
4. Excess objective: a flat or nearly flat day gives no blocks; a 1.50 kr hour 17–18 on a 0.50 kr day gives exactly `17:00-18:00`; ties give the same plan on every run (earliest start, then shortest block).
5. Indoor correction: laundry p10 22.0 → 100 %, 21.5 → 50 %, ≤ 21.0 → 0; kitchen p10 below floor → 0; `m` below 1 h after correction → no blocks.
6. Missing inputs: prices missing or incomplete, fewer than 18 forecast entries, p10 unavailable, unknown or non-numeric → nothing written. Factor or threshold at 0 → built-in default; anchors at 0 → no blocks.
7. Idempotence and slots: a slot already dated tomorrow → nothing written; the plan goes to A unless A is dated today, otherwise to B; the write is a blocking `input_text.set_value`.
8. DST: 92 and 100 quarters → empty plan.
9. Midnight boundary: today's block ending at 24:00 and at 23:30 (gap carried over); stale or missing today slot (tomorrow starts free).
10. Price timestamps as `datetime` objects and as ISO strings give the same plan.

### Live verification

1. `check_config` returns valid; reload `input_boolean`, `input_number`, `input_text`, `template`, `statistics`, `automation`, `python_script`. A new package may need a full restart before its entities appear; if a reload does not pick them up, Rickard is asked before restarting.
2. Set every helper to its built-in default and turn the master switch on.
3. Run the planner manually for tomorrow; check the written slot, the time the service call took, and that the plan looks right against the prices.
4. Render the binary sensor template against a test plan for today and check on/off against the clock.
5. The dashboard card shows both plans and "Ingen plan för imorgon" when a slot is cleared; categories are assigned.
6. Rickard (about 5 minutes the next day): heating is blocked at the planned times, and the old automation is gone.
