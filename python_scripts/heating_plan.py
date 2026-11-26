# Plans tomorrow's heat pump blocks from Nordpool prices, the SMHI forecast and
# the indoor p10 temperatures, and writes the plan to a plan slot.
#
# Called as python_script.heating_plan with data {"forecast": [...]}.
# Written for the python_script sandbox (RestrictedPython): no augmented
# assignment to subscripts, no names starting with an underscore, no imports.

PRICE_ENTITY = "sensor.nordpool_kwh_se3_sek_3_095_0"
LAUNDRY_ENTITY = "sensor.tvattstugan_p10_24h"
KITCHEN_ENTITY = "sensor.koket_p10_24h"
SLOT_A = "input_text.heating_plan_a"
SLOT_B = "input_text.heating_plan_b"

ANCHOR_TEMPS = [-7.5, -2.5, 2.5, 7.5]
ANCHOR_ENTITIES = [
    "input_number.heating_block_cold",
    "input_number.heating_block_chilly",
    "input_number.heating_block_mild",
    "input_number.heating_block_warm",
]
ANCHOR_DEFAULTS = [4.0, 8.0, 10.0, 12.0]
PAUSE_ENTITY = "input_number.heating_min_pause"
PAUSE_DEFAULT = 2.0
EXCESS_ENTITY = "input_number.heating_min_excess"
EXCESS_DEFAULT = 0.20
LAUNDRY_FULL_DEFAULT = 22.0
KITCHEN_FLOOR_DEFAULT = 21.0

QUARTERS_PER_DAY = 96
MIN_FORECAST_ENTRIES = 18
COLDEST_HOURS = 6
QUARTER_EPSILON = 1e-9
SUM_EPSILON = 1e-9
MIN_BLOCK_QUARTERS = 8
RECOVERY_WINDOW_QUARTERS = 96


def read_number(entity_id):
    """The numeric state of an entity, or None when missing or not a number."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    try:
        value = float(state.state)
    except (ValueError, TypeError):
        return None
    if value != value or abs(value) > 1e12:
        return None
    return value


def read_helper(entity_id, default, zero_is_default):
    """A helper value, falling back to the built-in default."""
    value = read_number(entity_id)
    if value is None:
        return default
    if zero_is_default and value == 0:
        return default
    return value


def slot_is_dated(entity_id, iso_date):
    """True when the slot text starts with `<iso_date> `."""
    state = hass.states.get(entity_id)
    if state is None:
        return False
    return str(state.state)[:11] == iso_date + " "


def to_datetime(value):
    """An aware datetime from a datetime or an ISO string, or None."""
    if isinstance(value, str):
        value = dt_util.parse_datetime(value)
    if value is None or value.isoformat is None:
        return None
    return dt_util.as_local(value)


def is_list(value):
    # No hasattr, and `list` is a function in the sandbox. The sandbox getattr
    # returns None for a missing attribute, so this is a duck-type check.
    return value.append is not None


def is_dict(value):
    return value.get is not None


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def read_quarters(first_ts, last_ts):
    """Tomorrow's prices as a list of quarter prices, or None (after logging)."""
    state = hass.states.get(PRICE_ENTITY)
    raw = None
    if state is not None:
        raw = state.attributes.get("raw_tomorrow")
    if not is_list(raw) or len(raw) == 0:
        logger.error("heating_plan: no raw_tomorrow prices")
        return None
    entries = []
    for entry in raw:
        if not is_dict(entry):
            logger.error("heating_plan: malformed price entry")
            return None
        start = to_datetime(entry.get("start"))
        end = to_datetime(entry.get("end"))
        value = entry.get("value")
        if start is None or end is None or not is_number(value):
            logger.error("heating_plan: price entry with missing start, end or value")
            return None
        entries.append([dt_util.as_timestamp(start), dt_util.as_timestamp(end), value])
    entries = sorted(entries)
    if abs(entries[0][0] - first_ts) > 1:
        logger.error("heating_plan: prices do not start at tomorrow 00:00")
        return None
    quarters = []
    expected_start = first_ts
    for entry in entries:
        length = entry[1] - entry[0]
        if abs(entry[0] - expected_start) > 1:
            logger.error("heating_plan: gap or overlap in the prices")
            return None
        if abs(length - 900) > 1 and abs(length - 3600) > 1:
            logger.error("heating_plan: price slot is neither 15 nor 60 minutes")
            return None
        quarters = quarters + [entry[2]] * int(length / 900.0 + 0.5)
        expected_start = entry[1]
    if abs(expected_start - last_ts) > 1:
        logger.error("heating_plan: prices do not reach the end of tomorrow")
        return None
    return quarters


def coldest_mean(first_ts, last_ts):
    """Mean of the 6 lowest forecast temperatures inside tomorrow, or None."""
    forecast = data.get("forecast")
    if not is_list(forecast):
        logger.error("heating_plan: no forecast")
        return None
    temps = []
    for entry in forecast:
        if not is_dict(entry):
            continue
        moment = to_datetime(entry.get("datetime"))
        temp = entry.get("temperature")
        if moment is None or not is_number(temp):
            continue
        ts = dt_util.as_timestamp(moment)
        if ts >= first_ts - 1 and ts < last_ts - 1:
            temps.append(temp)
    if len(temps) < MIN_FORECAST_ENTRIES:
        logger.error("heating_plan: only %s forecast entries inside tomorrow" % len(temps))
        return None
    coldest = sorted(temps)[:COLDEST_HOURS]
    return sum(coldest) / float(len(coldest))


def daily_block_hours(temp):
    """Most hours blocked in a day at a temperature, interpolated between the helper anchors."""
    values = [max(0.0, read_helper(ANCHOR_ENTITIES[i], ANCHOR_DEFAULTS[i], False)) for i in range(4)]
    if temp <= ANCHOR_TEMPS[0]:
        return values[0]
    if temp >= ANCHOR_TEMPS[3]:
        return values[3]
    for i in range(3):
        if temp <= ANCHOR_TEMPS[i + 1]:
            share = (temp - ANCHOR_TEMPS[i]) / (ANCHOR_TEMPS[i + 1] - ANCHOR_TEMPS[i])
            return values[i] + (values[i + 1] - values[i]) * share
    return values[3]


def floor_quarters(hours):
    return int(hours * 4 + QUARTER_EPSILON)


def pause_quarters():
    """The minimum pause between blocks, in whole quarters (at least one)."""
    return max(1, floor_quarters(read_helper(PAUSE_ENTITY, PAUSE_DEFAULT, True)))


def parse_quarter(text):
    """`HH:MM` on a quarter boundary to a quarter index (24:00 = 96), or None."""
    if len(text) != 5 or text[2] != ":":
        return None
    # Not str.isdigit: it accepts superscript digits, which int() rejects.
    for index in [0, 1, 3, 4]:
        if text[index] not in "0123456789":
            return None
    minutes = int(text[3:])
    quarter = int(text[:2]) * 4 + minutes // 15
    if minutes % 15 != 0 or minutes >= 60 or quarter > QUARTERS_PER_DAY:
        return None
    return quarter


def carried_gap(today_iso, pause):
    """First free quarter tomorrow, from the pause after today's last valid block."""
    for entity_id in [SLOT_A, SLOT_B]:
        if not slot_is_dated(entity_id, today_iso):
            continue
        blocks_text = str(hass.states.get(entity_id).state)[11:].split("|")[0]
        last = None
        for piece in blocks_text.split(","):
            ends = piece.split("-")
            if len(ends) != 2:
                continue
            start = parse_quarter(ends[0])
            end = parse_quarter(ends[1])
            if start is not None and end is not None and start < end:
                last = [start, end]
        if last is None:
            return 0
        return max(0, last[1] + pause - QUARTERS_PER_DAY)
    return 0


def block_values(prices, m, excess):
    """values[i][L]: the worth of blocking quarters [i, i + L).

    The slab floor and a compressor capped near its normal power spread the
    repayment of a block over a day or more, so a block is valued against the
    mean price of the 24 h after it: sum(price - window mean - excess). That
    lets the cheap night count for a morning peak as well as an evening one.
    Quarters of the window past midnight count at the day mean, since the
    next day's prices are unknown.
    """
    n = QUARTERS_PER_DAY
    prefix = [0.0]
    for price in prices:
        prefix.append(prefix[-1] + price)
    day_mean = prefix[n] / float(n)
    values = []
    for i in range(n):
        row = [0.0] * (m + 1)
        for length in range(MIN_BLOCK_QUARTERS, min(m, n - i) + 1):
            end = i + length
            window_end = min(end + RECOVERY_WINDOW_QUARTERS, n)
            unknown = RECOVERY_WINDOW_QUARTERS - (window_end - end)
            window_sum = prefix[window_end] - prefix[end] + unknown * day_mean
            reference = window_sum / float(RECOVERY_WINDOW_QUARTERS)
            row[length] = prefix[end] - prefix[i] - length * (reference + excess)
        values.append(row)
    return values


def optimise(prices, b, pause, excess, first_free):
    """Blocks as [[start, end], ...] quarter indices (end exclusive).

    Interval DP: g[i][u] is the best total block value from quarter i to the
    end of the day when quarter i is free and u quarters of the daily limit b
    are spent. A block may use the whole limit; blocks are `pause` apart.
    """
    n = QUARTERS_PER_DAY
    values = block_values(prices, b, excess)

    g = [None] * (n + 1)
    g[n] = [0.0] * (b + 1)
    for i in range(n - 1, -1, -1):
        row = list(g[i + 1])
        row_values = values[i]
        for length in range(MIN_BLOCK_QUARTERS, min(b, n - i) + 1):
            block_sum = row_values[length]
            if block_sum <= SUM_EPSILON:
                continue
            after = g[min(i + length + pause, n)]
            for u in range(b - length + 1):
                value = block_sum + after[u + length]
                if value > row[u]:
                    row[u] = value
        g[i] = row

    blocks = []
    i = first_free
    u = 0
    while i < n:
        target = g[i][u]
        chosen = 0
        for length in range(MIN_BLOCK_QUARTERS, min(b - u, n - i) + 1):
            block_sum = values[i][length]
            if block_sum <= SUM_EPSILON:
                continue
            value = block_sum + g[min(i + length + pause, n)][u + length]
            if abs(value - target) <= SUM_EPSILON:
                chosen = length
                break
        if chosen == 0:
            i = i + 1
        else:
            blocks.append([i, i + chosen])
            u = u + chosen
            i = min(i + chosen + pause, n)
    return blocks


def format_quarter(quarter):
    """Quarter index to HH:MM; 96 gives 24:00."""
    return "%02d:%02d" % (quarter // 4, (quarter % 4) * 15)


def format_blocks(blocks):
    return ",".join([format_quarter(b[0]) + "-" + format_quarter(b[1]) for b in blocks])


def write_plan(tomorrow_iso, blocks_text, info_text):
    if slot_is_dated(SLOT_A, dt_util.now().date().isoformat()):
        slot = SLOT_B
    else:
        slot = SLOT_A
    value = tomorrow_iso + " " + blocks_text + "|" + info_text
    hass.services.call("input_text", "set_value", {"entity_id": slot, "value": value}, True)


def main():
    today = dt_util.now().date()
    tomorrow = today + datetime.timedelta(days=1)
    tomorrow_iso = tomorrow.isoformat()

    # Step 1: already planned for tomorrow, nothing to do.
    if slot_is_dated(SLOT_A, tomorrow_iso) or slot_is_dated(SLOT_B, tomorrow_iso):
        return

    # Step 2: prices.
    first_ts = dt_util.as_timestamp(dt_util.start_of_local_day(tomorrow))
    last_ts = dt_util.as_timestamp(dt_util.start_of_local_day(tomorrow + datetime.timedelta(days=1)))
    quarters = read_quarters(first_ts, last_ts)
    if quarters is None:
        return
    if len(quarters) != QUARTERS_PER_DAY:
        write_plan(tomorrow_iso, "", "t=na;l=na;k=na;c=na;b=0.00;p=na;e=na")
        return

    # Step 3: outdoor temperature.
    outdoor = coldest_mean(first_ts, last_ts)
    if outdoor is None:
        return

    # Step 4: indoor temperatures.
    laundry = read_number(LAUNDRY_ENTITY)
    kitchen = read_number(KITCHEN_ENTITY)
    if laundry is None or kitchen is None:
        logger.error("heating_plan: a p10 sensor is unavailable, unknown or not a number")
        return

    # Step 5: daily block limit and correction.
    base = daily_block_hours(outdoor)
    full = read_helper("input_number.heating_laundry_full_p10", LAUNDRY_FULL_DEFAULT, True)
    floor = read_helper("input_number.heating_kitchen_floor_p10", KITCHEN_FLOOR_DEFAULT, True)
    laundry_c = min(1.0, max(0.0, 1.0 - (full - laundry)))
    kitchen_c = 0.0 if kitchen < floor else 1.0
    correction = min(laundry_c, kitchen_c)

    # Step 6: daily block limit and pause in whole quarters.
    b = floor_quarters(base * correction)
    pause = pause_quarters()
    excess = max(0.0, read_helper(EXCESS_ENTITY, EXCESS_DEFAULT, True))

    # Step 7: optimise and write.
    blocks = []
    if b >= MIN_BLOCK_QUARTERS:
        blocks = optimise(quarters, b, pause, excess, carried_gap(today.isoformat(), pause))
    # Avoid formatting a tiny negative mean as t=-0.0.
    if abs(outdoor) < 0.05:
        outdoor = 0.0
    info = "t=%.1f;l=%.2f;k=%.2f;c=%.2f;b=%.2f;p=%.2f;e=%.2f" % (
        outdoor, laundry, kitchen, correction, b / 4.0, pause / 4.0, excess)
    write_plan(tomorrow_iso, format_blocks(blocks), info)


main()
