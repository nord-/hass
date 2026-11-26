# Heat pump price plan: review of the model against measured behaviour

> Independent review, saved verbatim. It describes the model as it was on 2026-11-26 before that day's changes: a 12 h recovery window, a 1 h minimum block and a fixed 0.10 margin. What was done with it, and which findings the owner rejected (the immersion heater, Felix's room as a guard), is in `docs/varmepump-prisplan-lardomar.md`. The scripts and data files it names were in a temporary folder and are not kept in the repo.

Date: 2026-11-26. Read-only review; nothing in the repo or in Home Assistant was changed.

## Short answers

| Claim | Verdict |
|---|---|
| 1. The 12 h recovery window is too short; 24 h fits better | **Supported by the data, but it barely matters for the outcome.** A flat 12 h kernel is among the worst-fitting shapes; an exponential with a time constant around 24 h (12 to 48 h not separable) fits best. Only about a quarter to a third of the missed energy shows up within 12 h, about half within 24 h. In a simulation on 126 real price days, a 24 h window beats 12 h by about 0.07 SEK/day (2 to 3 %). |
| 2. A morning block is thermally cheap, so two blocks can beat one long afternoon block | **Split verdict.** The thermal part is not supported: a blocked morning hour costs the rooms as much as a blocked afternoon hour (dip area within 24 h: laundry −3.4 vs −3.8 °C·h per blocked hour, kitchen −3.5 vs −3.6, intervals overlap). The economic part is mildly supported, for a different reason than the owner's: when the day's highest prices are in the morning, two blocks are worth more. Best two-block plan beats best one-block plan on about 65 % of days, by 0.33 SEK/day on average, by more than 1 SEK on about 10 % of days. The planner already writes two or more blocks on 41 % of days. |
| 3. Blocked energy is repaid one for one | **Not supported.** Three independent estimates put the share bought back within three days at roughly half (range 40 to 75 %). The rest is visible as a cooler house: about 0.15 to 0.2 °C lower daily mean per blocked hour per day, sustained. Whether the repaid energy is produced at a different efficiency **cannot be determined from this data** (no heat-side measurement). |

The finding that matters most is not on the list of claims: because roughly half of the blocked energy is never bought back, the plan is to a large degree a temperature setback, and the daily limit (not the price objective) decides both the money and the comfort. All four variants of the price objective I tested land within 5 % of each other.

## Data and method

- Hourly long-term statistics 2025-10-30 to 2026-11-26 (`stats.json`, fetched in small chunks by `fetch.py`), 5-minute statistics from 2026-11-10 (`stats5.json`), switch history and plan slots over REST (`rest_out.json`).
- **The compressor is on phase 3 alone** (`sensor.shelly_3em_c45bbe55c55e_power_2`); phases 1 and 2 carry about 45 W of controls plus the immersion heater. All energy figures below are compressor energy on that phase, immersion heater excluded.
- **Block detection for last winter**: an hour is a full outage when the hourly maximum of the compressor phase is below 30 W. Checked against exact switch history since 2026-11-10: 50 of 56 fully blocked hours are caught, and the false positives are natural idling, which only occurs above about +4 °C outdoors (off share is a flat 14 to 16 % of hours in every band below +4 °C, then rises). To remove idling, an off hour counts as blocked only if its price is in the upper half of its day (or, since 2026-11-10, if the switch history says so). Hours with partial off-time count as half.
- "Outage" below means compressor-off time, which is the physically relevant quantity; it is 1 to 2 h/day longer than the blocked time (see finding 8).
- The old automation blocked on price only, so block timing is tied to hour of day. Every regression has 24 hour-of-day intercepts, outdoor temperature now and as 6 h, 24 h and 25 to 72 h means, and PV production now, last 6 h and last 24 h (a direct proxy for sun on the house). Uncertainty is from resampling whole weeks.
- A placebo check passes: outage hours that lie in the *future* explain nothing. Hourly, the coefficients for outage 3 to 26 h ahead are −0.009 to 0.000 kW per outage hour (the real lag terms are +0.01 to +0.05); daily, tomorrow's outage hours have −0.06 kWh (se 0.10) on today's energy and −0.005 to +0.03 °C (se 0.02 to 0.03) on today's room temperatures. That argues against the result being driven by weather that happens to coincide with expensive days. Wind is not measured and cannot be ruled out.

## Findings, ranked by expected effect on cost and comfort

### 1. About half of the blocked energy is never bought back; it is a cooler house instead

**Claim tested:** the model's assumption that every blocked kWh is bought back later.

**Evidence (data supports this):**

- *Hourly distributed-lag fit* (`dl.py`, 2 132 fully-running hours with 24 h outdoor mean below 6 °C): extra compressor power per earlier outage hour sums to +0.24 kWh within 12 h (90 % interval 0.11 to 0.37), +0.47 within 24 h (0.31 to 0.69), +0.67 within 48 h, +0.75 within 72 h (0.51 to 1.06). The compressor would have drawn 1.0 to 1.2 kW in those outage hours, so 60 to 75 % comes back within three days if every later hour is running.
- *Daily energy* (`daily2.py`, 86 days with mean outdoor below 4 °C and no immersion heater): compressor kWh per blocked-outage hour is −1.20 the same day (se 0.10), +0.43 the next day (se 0.10), +0.08 and −0.04 on days 2 and 3. Net −0.74 kWh against 1.26 kW running power: about 42 % bought back. Below 0 °C (48 days): −1.60, +0.39, net about 16 to 25 %. Between 0 and 4 °C (38 days): about 61 %.
- *3-day and 7-day totals* (`agg.py`): −0.56 kWh per outage hour (se 0.24) on 3-day periods, −0.70 (se 0.54) on weeks: 53 % and 37 % bought back inside the period.
- *Room temperatures, independent sensors* (`daily2.py`): daily mean per blocked-outage hour is −0.03 °C the same day, **−0.10 to −0.13 the next day**, −0.03 to −0.04 on day 2, −0.02 on day 3, in laundry, kitchen, living room, office and two of the three LYS sensors (se about 0.02 each; next-day placebo +0.01). Sum: −0.18 to −0.24 °C per sustained blocked hour per day. On 3-day and 7-day aggregates the same figure is −0.08 to −0.21.
- *Raw matched days* (`misc1.py`): at −10 to −2 °C outdoors the laundry room averaged 23.7 °C after 0 to 6 outage hours in the previous two days (n=5), 23.1 after 6 to 12 h (n=12) and 22.3 after more than 12 h (n=15), with the same daily compressor energy (27.5, 26.9, 27.3 kWh). Kitchen 23.1, 22.5, 21.8.
- The two halves agree with each other: 0.5 kWh of electricity not bought per blocked hour is about 1.5 kWh of heat per day, and a house that loses about 0.25 to 0.3 kW/K (from the slope of energy against outdoor temperature) cools 0.2 °C for that.

**Confidence:** moderate that the share is clearly below one (the estimates are 2 to 3.5 standard errors from full repayment); low on the exact value. Not excluded: repayment that continues beyond 72 h, and the wood stove being lit more when the house is cool, which would be repayment the data cannot see.

**Plausible but the data cannot show it:** the physical reason. With curve-only control the pump aims at a supply temperature, not at a room temperature, so nothing in the controller knows a debt exists; the only feedback is colder return water.

**What it changes:** the money first. On 126 real price days at last winter's prices (mean spot 0.91 SEK), the current plan saves about 7.8 SEK/day in cash if 60 % is bought back, of which only about 2.8 SEK is price shifting; the other 5 SEK is energy not bought, paid for with temperature. With one-for-one repayment the saving would be 3.0 SEK/day. So: about two thirds of what the plan saves is setback, not shifting. Second, "fees and VAT only scale the objective" holds only for the shifted part. Third, the comparison "house about 1 °C warmer under the new plan" does not survive: compressor-off time was 10, 8, 9 and 9.5 h on 22 to 25 Nov against 12, 7, 10.5 and 5.5 h on 17 to 20 Nov, and the difference in room temperature is explained by PV production of 11 kWh on both 21 and 22 Nov against 0.1 to 3 kWh on the other days. Since 22 Nov the laundry daily mean has fallen 23.70, 23.40, 23.15, 22.79.

### 2. The daily limit is the main dial, and its last hours earn little

**Claim tested:** that the limit is "a ceiling, not a target" and the anchors (4/8/10/12 h) are roughly right.

**Evidence (model-based, on real prices; `sim.py`, `sim2.py`):** the simulation uses a one-node house with deficit, time constant 24 h and 60 % buy-back (alternatives 12 h/80 %, 24 h/100 %, 48 h/50 % give the same picture), measured normal power per hour, measured ramp-up loss, and counts a "comfort-neutral" saving: cash saving minus the never-bought energy priced at the mean of the following three days.

| Cap on the daily limit | Hours blocked per day | Comfort-neutral saving, SEK/day | Cash saving, SEK/day |
|---|---|---|---|
| 2 h | 1.9 | 1.19 | 3.08 |
| 4 h | 3.8 | 2.07 | 5.55 |
| 6 h | 5.2 | 2.50 | 6.95 |
| 8 h | 6.1 | 2.72 | 7.66 |
| anchors as today | 6.3 | 2.77 | 7.84 |

The first two hours are worth 0.6 SEK each in shifting; the hours beyond four are worth under 0.3 SEK each, and each costs the same 0.15 to 0.2 °C. In practice the limit *is* a target: the plan used 6.3 of 7.4 allowed hours on average, and 8.25, 7.25, 6.5 and 8.0 h on 22 to 25 Nov.

Raising the 0.10 margin does the same job more selectively: 0.20 gives 4.75 h/day and 2.64 SEK (−5 % shifting value for −25 % blocked time); 0.30 gives 2.9 h and 2.28 SEK. 31 % of the days (spot range above 1 SEK) deliver 69 % of the shifting value.

**Confidence:** moderate on the shape (it holds under all four parameter sets), low on absolute SEK. At this November's price level (daily mean spot 1.0 to 3.2 SEK) the figures scale up roughly two to three times.

**What it changes:** at −2.5 °C the anchors allow 8 h/day, which at the measured rate is a house about 1.2 to 1.6 °C cooler than without blocks once it has settled. Whether that is wanted is the owner's call, but it should be chosen, not arrive as a side effect. Direction: fewer hours at the mild end or a higher margin; rough size −1.5 to −2.5 h/day for −0.15 to −0.5 SEK/day of shifting value (plus 2 to 4 SEK/day less "saving" from a cooler house).

### 3. The comfort guard looks in the wrong place and too late

**Claim tested:** that the laundry p10 correction and the per-calendar-day limit keep the house from getting cold.

**Evidence (data supports this):**

- **The dip comes after the block, not during it.** For the long blocks of 22 to 24 Nov (5-minute data, `proxy.py`): laundry 24.25 at block start, 23.50 at release, minimum 23.08 at 03:35; kitchen 23.80, 23.11, minimum 22.35 at 05:40; living room minimum at 06:30 to 07:25; LYS2 minimum at 09:00 to 10:00. The winter regression says the same: the room effect per blocked hour is largest 9 to 18 h later (−0.17 to −0.22 °C per outage hour in that bin; `ampm.py`). "Rooms back 2 to 3 h after release" is not what the data shows.
- **The effect of a day's blocks peaks the next day** (three to four times the same-day effect). The p10 read at 13:12 on day D−1 for day D therefore mostly reflects blocks from D−3 and D−2.
- **The laundry room is one of the warmest monitored rooms.** Cold-season means: laundry 23.15, office 22.85, living room 22.73, kitchen 22.58, LYS1 21.88, LYS2 21.69. On the 15 days when laundry p10 was 21.8 to 22.3, the daily minimum was 21.2 in the kitchen, 20.8 at LYS1 and 20.3 at LYS2. LYS2 bottomed at 21.29, 20.89, 20.75 and 20.78 on the mornings of 23 to 26 Nov while the laundry p10 the planner read went 23.3, 23.1, 23.0, 22.6 and the correction stayed at 1.00. (LYS4 does not react to blocks at all, coefficient 0.00, and is useless as a guard.)
- **The limit is per calendar day, the house integrates over days.** The plans actually run blocked 11.25 h inside one 24 h window (ending 25 Nov 14:45) with limits of 6.5 and 8.0 h. The rule allows up to nearly twice the limit in 24 h (a block ending at midnight, a 2 h pause, the next day's block).
- Last winter, with about 5.4 outage hours per day, the approximated laundry p10 was below 22.0 on 19 % of January days and 39 % of February days, and the kitchen p10 below 21.0 on 13 % and 36 %. With limits of 8 h at −2.5 °C the correction will be active for much of the winter.

**Plausible but not yet observed:** with a gain of about 0.2 °C per blocked hour, a slope of 10 % per 0.1 °C and two days of delay, the loop gain is about 1.3 to 1.7. A toy loop with the measured day-by-day response (`misc2.py`) swings between about 3 and 7 h/day with a period of 5 to 6 days once p10 is inside the 21 to 22 band; it does not run away. The kitchen floor at 21.0 is a cliff on a sensor that cooking moves by 0.5 °C.

**Confidence:** high on timing, room ranking and the 11.25 h; low on the oscillation.

**What it changes:** comfort, not cost. Direction: the limit should see what was blocked in the previous 24 to 48 h (known exactly at planning time, no sensor lag), and the guard room should be the coldest room the owner cares about. Rough size: the correction would have started about two days earlier this week.

### 4. Below about −5 °C a block can be repaid by the immersion heater, and the compressor has almost no headroom

**Evidence (data suggests, small sample; `misc1.py`):** last winter the immersion heater ran 74 hours, 129 kWh. In hours with a 6 h outdoor mean between −9 and −5 °C it ran in 16 of 206 hours that had more than 4 h of outage in the previous 24 h, and in 0 of 111 hours with 4 h or less. Below −9 °C it ran regardless. These hours cluster on a handful of days, so the effective sample is days, not hours. Separately, the fully-running compressor draws a median 1.79 kW at −10 to −5 °C against a 95th percentile of 2.17 kW: at most 0.3 to 0.4 kW of headroom, so 4 h of missed heat (about 7 kWh) cannot be recovered in less than about 20 h even at full speed. On 12 Jan (−14 °C) the old automation blocked 08 to 12 right after the heater had run 03 to 07.

**Confidence:** low to moderate. **Cannot be determined** from last winter alone whether the blocks caused the heater hours; one more cold spell with the heater current logged against the plan would settle it.

**What it changes:** one heater hour at 3 kW costs about what two days of shifting earn. The planner still allows 4 h at −7.5 °C and about 6 h at −5 °C. Direction: much less blocking below about −5 °C. Size: the 16 heater hours in that band were about 30 kWh last winter, so tens of SEK up to perhaps a hundred per winter, concentrated in the coldest and most expensive days. Small in money; it ranks here because it is the one place where a block is clearly repaid at a worse efficiency.

### 5. Recovery window: 12 h is too short, and it almost does not matter (claim 1)

**Evidence (data supports the first half; `kernel.py`):** with one outage term added to the weather model, the residual sum of squares falls by 5.8 % for a flat 12 h window, 8.4 % for flat 24 h, 8.9 % for flat 36 h, 9.8 % for an exponential with a 24 h time constant and 10.7 % for the same with a 2 h dead time. Time constants of 6 h and 96 h are as poor as flat 12 h; 12 to 48 h cannot be told apart. Below 0 °C nothing net comes back in the first 12 h at all (+0.01 kWh per outage hour, interval −0.15 to +0.21; in the first two hours after an outage the compressor runs *below* normal, −0.23 kW per outage hour, which is the ramp-up of finding 8), and the best fits are 24 to 48 h. Between 0 and 6 °C about 55 % is back in 12 h and the best fits are 12 to 24 h. So the window should really grow as it gets colder.

**Evidence (model-based; `sim.py`):** comfort-neutral saving in SEK/day for the same limits and constraints:

| Reference price | 24 h / 60 % | 12 h / 80 % | 24 h / 100 % | 6 h / 100 % (the planner's own assumption) |
|---|---|---|---|---|
| 12 h after the block (today) | 2.77 | 2.88 | 2.89 | 3.09 |
| 24 h after the block | 2.84 | 2.92 | 2.94 | 3.06 |
| day mean (the first objective) | 2.90 | 2.96 | 2.99 | 3.06 |
| half day mean, half next 24 h | 2.86 | 2.93 | 2.96 | 3.06 |
| best plan with hindsight | 3.25 | 3.26 | 3.38 | 3.48 |

The spread between objectives is 0.03 to 0.13 SEK/day. The 12 h window only wins if its own assumption is true. Where it does matter is a specific day shape: the 12 h window covers the day's most expensive hour on 94 % of days against 98 % for the others, because the hours after a morning block are themselves expensive. Tomorrow (27 Nov, peak 4.37 SEK at 08 to 09, plan written 12:15 to 18:30) is such a day: every other reference blocks 08 to 11 and scores about 6.2 to 6.7 SEK against 3.4 to 4.2 for the written plan, under all three parameter sets (prices after 27 Nov assumed to repeat).

**A structural flaw neither of us had listed:** the reference of an early block includes the hours of a later block, when nothing can be repaid. This is the mechanism behind the 94 %.

**Confidence:** high that flat 12 h is the wrong shape; moderate that changing it is worth only a few percent.

**What it changes:** on roughly one day in fifteen the morning peak is added and 2 to 3 SEK gained; on the others the plan moves by an hour or not at all. The day-mean and blended references produce more blocks (1.5 to 1.6 per day against 1.4), including isolated 1 h blocks.

### 6. Morning against afternoon (claim 2)

**Evidence (data; `ampm.py`, last winter, outage split by the hour in which it happened, 190 morning and 367 afternoon/evening outage hours):**

- Room cost per blocked hour is the same. Dip area within 24 h: laundry −3.4 °C·h (morning, interval −4.5 to −2.2) against −3.8 (afternoon, −5.8 to −2.3); kitchen −3.5 against −3.6; living room −3.1 against −3.4. Within 72 h: −6.7 against −5.8 in the laundry.
- On dull days only (PV below 3 kWh in the previous 24 h, 86 morning outage hours) the morning dip within 24 h is smaller (−0.5, interval −2.8 to +1.6, against −4.5), but within 72 h it is the same (−5.5 against −6.5). This is the opposite of what a sun effect would give and the sample is thin; I read it as noise.
- Energy bought back within 24 h: +0.16 kWh per morning outage hour (interval −0.64 to +0.74) against +0.61 per afternoon hour (0.34 to 0.83). The direction fits the owner's "no debt" argument, but the intervals overlap and the room temperatures say the missing repayment is paid in temperature.
- The timing differs: a morning block puts the dip into the afternoon and evening, an afternoon block into the night and early morning.
- A blocked morning hour displaces more energy: running power is 1.31 to 1.40 kW at 05 to 08 and 1.09 to 1.10 kW at 16 to 18 (about 25 % more), at outdoor temperatures about 2 to 3 °C lower.

**Evidence (model-based):** the best two-block plan beats the best one-block plan on 63 to 68 % of days by 0.3 to 0.4 SEK/day on average and by more than 1 SEK on 9 to 14 % of days, with the same or a slightly higher peak deficit because it uses about half an hour more. The day's most expensive hour falls before noon on 36 % of days.

**Confidence:** moderate that there is no large thermal advantage to mornings; low on anything finer. **Cannot be determined from this data:** whether "07 to 10 and 16 to 19" beats "one afternoon block of the same total length" in room temperature. An alternating-day test settles it (see experiments).

**What it changes:** nothing needs to be forced. The optimiser already splits when the prices say so, and it would split more with a longer or flatter reference (finding 5).

### 7. Day-to-day price level is as large as the within-day spread

**Evidence (data, `misc2.py`):** the mean spot price of the following two days relative to the planned day has a 10th to 90th percentile of 0.48 to 2.16. With repayment spread over one to three days, a block on a cheap day followed by expensive days loses money even at that day's peak: under 24 h time constants the plan's comfort-neutral result is negative on 21 % of days (5 % under the planner's own 6 h assumption), standard deviation 4.2 SEK around a mean of 2.8. The plans of 22 and 23 Nov are examples (−2.6 and −2.8 SEK: blocked at 1.4 to 2.0 SEK, repaid on days averaging 1.6 to 2.5).

**Confidence:** high on the price statistics, model-dependent on the consequence. **What it changes:** nothing that tomorrow's prices alone can fix; it bounds what any objective can achieve, and it is a reason not to tune the reference window further.

### 8. Every block costs 0.4 to 0.8 h of extra outage, and the release behaviour has two modes

**Evidence (5-minute data, `release.py`, `misc1.py`):** for the five releases 22 to 25 Nov with at least 6 h of running afterwards, the first three hours delivered 0.42, 0.66, 0.82, 0.83 and 0.66 h less than the level reached in hours 4 to 6. Two modes: either the compressor starts within 5 minutes and peaks at 2.4 to 2.8 kW in the first hour (three of five; that power level is the hot-water signature, so the first 30 to 90 minutes go to the tank, not the floor), or it starts about 25 minutes later and climbs from 0.3 to 1.7 kW in steps over about two hours (two of five, both after the longest blocks, peak 1.6 to 1.7 kW). This matches the coordinator's corrected delays (1 to 43 min); the hot-water explanation for the immediate starts fits 3 of 3 and is not proven. Daily compressor-off time was 10, 8, 9 and 9.5 h on days with 8.25, 7.25, 6.5 and 8.0 h blocked.

**Observation on the fixed constraints (not a recommendation):** this supports both. The old automation's 15-minute blocks of 19 and 20 Nov were each followed by 25 to 75 minutes without the compressor (longer where the wait ran into the next block), and a 2 h pause delivers roughly 1.2 to 1.5 h worth of normal heating. Every additional block adds roughly 0.7 h of outage that the daily limit does not count.

**Confidence:** moderate (n=5).

### 9. Smaller things checked

- **"A blocked hour displaces the same energy at any time"**: no, by about ±13 %. Fully-running compressor power by hour on cold days: 1.40 kW at night, 1.22 at 09 to 10, 1.35 at 12 to 13, 1.09 at 16 to 18. The pump follows roughly the previous six hours of outdoor temperature (−0.10 kW per °C), not the current one. Second-order for placement.
- **Prices after midnight valued at the day mean**: biased. The day mean overstates the first 6 h of the next day by 41 % (+0.26 SEK spot, 206 days) and the first 12 h by 10 %; it is unbiased for the whole next day. Replacing it with the planned day's same hours made the simulated result *worse* by 0.1 to 0.2 SEK/day, because the bias works as a margin against long evening blocks. Leave it.
- **"Price paid relative to the day's mean" (0.90 to 0.92)** is not a measure of success. An unblocked pump scores 1.00 (0.98 to 1.02), removing the blocked hours gives 0.92 by construction, and the figure ignores both the energy repaid on later days and the energy never bought.
- **Hot water** is about 0.7 kWh/day of compressor energy in the recent weeks (4 %), too small to matter for the objective.
- **Efficiency of repaid energy:** cannot be determined. For orientation only: afternoon blocks are repaid at outdoor temperatures about 1.5 to 2.5 °C lower, morning blocks about 3 °C higher for the part repaid the same day (mean outdoor by hour on cold days: −2.9 °C at 06, +1.4 at 13, −2.4 at 23). The extra compressor power during catch-up is small (about +0.3 kW after an 8 h block), so a part-load penalty is unlikely to be large.

## What cannot be determined from this data, and what would settle it

| Open question | Why not | Observation or experiment |
|---|---|---|
| Exact buy-back share and time constant | No block-free reference days since the plan started; last winter's blocks are tied to price and hour | Leave two days a week unblocked, chosen by calendar and not by price, for six to eight cold weeks. Daily energy scatters by 2.5 kWh around the weather model, so about 15 clean days give the share to about ±15 points. |
| Efficiency of repaid energy; why half is not repaid | No heat-side measurement | Two temperature probes on the underfloor supply and return pipes (or the controller's own values). With flow roughly constant this gives heat output, COP by hour and the debt directly, within a week. |
| Two blocks against one afternoon block of the same length | The old automation never ran clean versions of either | Alternate the two shapes day by day with equal hours. To see 1 kWh/day or 0.3 °C needs about 25 days per shape. |
| Whether blocks trigger the immersion heater at −5 to −9 °C | Six clustered days | Heater current against the previous 24 h of blocked hours through one cold spell. |
| Wood stove as hidden repayment | Not logged | A note of the evenings it was lit, or a temperature sensor near it. |
| Whether room thermostats or actuators close floor loops | Unknown to me | Ask the owner; it would change how return temperature responds after a block. |

## Changes I would make first

1. **Set the daily limit from the measured exchange rate, deliberately.** One blocked hour per day costs about 0.15 to 0.2 °C sustained and earns under 0.3 SEK/day in shifting once past four hours. Either lower the anchors at the mild end or raise the margin to about 0.20 (−25 % blocked time for −5 % shifting value). This is the largest effect on both comfort and money, and the owner should pick the number.
2. **Make the limit and the comfort guard see the last one to two days.** Count the hours blocked in the previous 24 to 48 h against the limit instead of resetting at midnight, and guard on the coldest room that matters (LYS2 or LYS1 run 1.3 to 1.5 °C below the laundry room and reach their minimum the morning after a block).
3. **Cut blocking below about −5 °C** until the immersion heater question is settled: the compressor has 0.3 to 0.4 kW of headroom there and the heater ran only after more than 4 h of outage.

If the objective is touched at all, a 24 h window (or half day mean, half next 24 h) is the better-supported shape and fixes the missed morning peaks. Expect 2 to 3 % on average and 2 to 3 SEK on days like 27 Nov, no more.

## Changes I would explicitly not make yet

- **A rule that forces two blocks or favours mornings.** The data shows no thermal advantage, and the optimiser already splits on price.
- **Another refinement of the reference window beyond one simple step.** All variants are within 5 % of each other and the day-to-day price level is the larger unknown.
- **A different stand-in for prices after midnight.** Tested, slightly worse.
- **An efficiency term for repaid energy or weights per hour of day.** Not measurable today, second-order by the bounds above.
- **Counting the unrepaid energy as a saving in the objective.** It would make the planner block as much as the limit allows on any day; that is a temperature decision and belongs in the limit.
- Minimum block length and the 2 h pause are fixed by the owner and the data supports them (finding 8); nothing here argues for shortening either.

## Files in this folder

`fetch.py`, `fetch5.py`, `rest.py` (read-only fetches); `load.py`, `load5.py`, `feat.py` (loading, outage detection, lag features); `explore1.py` to `explore3.py`, `chk_price.py` (detection and validation); `dl.py`, `kernel.py` (hourly repayment kernel); `placebo_daily.py`, `daily2.py`, `agg.py` (placebo, daily and multi-day energy and room temperature); `ampm.py` (morning against afternoon); `misc1.py`, `misc2.py`, `misc3.py`, `proxy.py`, `release.py` (immersion heater, ramp-up, p10 history, rolling 24 h, price stand-in, feedback toy, metric check); `sim.py`, `sim2.py`, `sim2b.py` (plan economics on real price days). Data: `stats.json`, `stats5.json`, `rest_out.json`, `daily.pkl`, `sim.pkl`.
