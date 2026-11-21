"""Tests for python_scripts/heating_plan.py, run in the python_script sandbox mirror."""

import datetime as dt
import json
import pathlib
from zoneinfo import ZoneInfo

import pytest

from ha_sandbox import FakeState, run_script

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = str(ROOT / "python_scripts" / "heating_plan.py")
FIXTURE = ROOT / "tests" / "fixtures" / "prices_2026-11-19.json"
LOCAL = ZoneInfo("Europe/Stockholm")
UTC = dt.timezone.utc

PRICE_ENTITY = "sensor.nordpool_kwh_se3_sek_3_095_0"
DEFAULT_HELPERS = {
    "input_number.heating_block_cold": "1",
    "input_number.heating_block_chilly": "3",
    "input_number.heating_block_mild": "4",
    "input_number.heating_block_warm": "6",
    "input_number.heating_budget_factor": "2.0",
    "input_number.heating_laundry_full_p10": "22.0",
    "input_number.heating_kitchen_floor_p10": "21.0",
}


def fixture_prices():
    """The fixture as the state machine holds it: aware datetime objects."""
    with open(FIXTURE, encoding="utf8") as fil:
        raw = json.load(fil)
    return [
        {
            "start": dt.datetime.fromisoformat(e["start"]),
            "end": dt.datetime.fromisoformat(e["end"]),
            "value": e["value"],
        }
        for e in raw
    ]


def contiguous_quarters(first_start, count, value=1.0):
    """`count` contiguous 15-minute entries from the aware datetime `first_start`."""
    # Step in UTC: aware arithmetic in a zone ignores DST jumps.
    first_start = first_start.astimezone(UTC)
    step = dt.timedelta(minutes=15)
    out = []
    for i in range(count):
        start = first_start + step * i
        out.append({"start": start, "end": start + step, "value": value})
    return out


def make_states(prices=None, laundry="22.5", kitchen="22.0", helpers=None,
                slot_a="", slot_b=""):
    prices = fixture_prices() if prices is None else prices
    states = {
        PRICE_ENTITY: FakeState("1.5", {"raw_tomorrow": prices}),
        "sensor.tvattstugan_p10_24h": FakeState(laundry),
        "sensor.koket_p10_24h": FakeState(kitchen),
        "input_text.heating_plan_a": FakeState(slot_a),
        "input_text.heating_plan_b": FakeState(slot_b),
    }
    merged = dict(DEFAULT_HELPERS)
    merged.update(helpers or {})
    for entity_id, value in merged.items():
        states[entity_id] = FakeState(value)
    return states


def make_forecast(temps, start_utc="2026-11-20T23:00:00+00:00"):
    first = dt.datetime.fromisoformat(start_utc)
    return [
        {"datetime": (first + dt.timedelta(hours=i)).isoformat(), "temperature": t}
        for i, t in enumerate(temps)
    ]


def parse_plan(value):
    """Split a plan string into (date, blocks, info)."""
    head, info_text = value.split("|")
    date, blocks_text = head.split(" ", 1)
    blocks = [b for b in blocks_text.split(",") if b]
    info = dict(piece.split("=") for piece in info_text.split(";"))
    return date, blocks, info


def run(states, forecast, now=None):
    return run_script(SCRIPT, states, {"forecast": forecast}, now)


def day(temp):
    return make_forecast([temp] * 24)


def planned(result):
    """The single written call as (entity_id, parsed plan)."""
    assert result.exception is None
    assert len(result.service_calls) == 1
    domain, service, data, _ = result.service_calls[0]
    assert (domain, service) == ("input_text", "set_value")
    return data["entity_id"], parse_plan(data["value"])


def info_of(result):
    return planned(result)[1][2]


def test_script_compiles():
    result = run(make_states(), day(-2.5))
    assert result.compile_errors == []
    assert result.exception is None


def test_budget_at_anchor():
    entity, (date, blocks, info) = planned(run(make_states(), day(-2.5)))
    assert entity == "input_text.heating_plan_a"
    assert date == "2026-11-21"
    assert (info["t"], info["c"], info["m"], info["b"]) == ("-2.5", "1.00", "3.00", "6.00")
    assert info["l"] == "22.50"
    assert info["k"] == "22.00"


def test_budget_between_anchors():
    info = info_of(run(make_states(), day(0.0)))
    assert (info["m"], info["b"]) == ("3.50", "7.00")


def test_budget_outside_anchors():
    info = info_of(run(make_states(), day(-10.0)))
    assert (info["m"], info["b"]) == ("1.00", "2.00")
    info = info_of(run(make_states(), day(10.0)))
    assert (info["m"], info["b"]) == ("6.00", "12.00")


def test_coldest_six_hours():
    info = info_of(run(make_states(), make_forecast([3.0] * 18 + [-7.0] * 6)))
    assert (info["t"], info["m"], info["b"]) == ("-7.0", "1.00", "2.25")


def test_laundry_correction():
    info = info_of(run(make_states(laundry="21.5"), day(-2.5)))
    assert (info["c"], info["m"], info["b"]) == ("0.50", "1.50", "3.00")
    info = info_of(run(make_states(laundry="21.0"), day(-2.5)))
    assert (info["c"], info["m"], info["b"]) == ("0.00", "0.00", "0.00")
    info = info_of(run(make_states(laundry="22.0"), day(-2.5)))
    assert info["c"] == "1.00"
    result = run(make_states(laundry="21.2"), day(-2.5))
    _, (_, blocks, info) = planned(result)
    assert (info["c"], info["m"], info["b"]) == ("0.20", "0.50", "1.00")
    assert blocks == []


def test_kitchen_floor():
    assert info_of(run(make_states(kitchen="20.9"), day(-2.5)))["c"] == "0.00"
    assert info_of(run(make_states(kitchen="21.0"), day(-2.5)))["c"] == "1.00"


def test_quarter_rounding_epsilon():
    states = make_states(laundry="21.9", helpers={"input_number.heating_block_chilly": "2.5"})
    assert info_of(run(states, day(-2.5)))["m"] == "2.25"


@pytest.mark.parametrize("factor", ["0", "unknown", "abc", None])
def test_helper_defaults_factor(factor):
    helpers = {"input_number.heating_budget_factor": factor}
    states = make_states(helpers=helpers if factor is not None else None)
    if factor is None:
        del states["input_number.heating_budget_factor"]
    info = info_of(run(states, day(-2.5)))
    assert info["b"] == "6.00"


def test_helper_defaults_thresholds_and_anchors():
    states = make_states(laundry="21.5", kitchen="20.9", helpers={
        "input_number.heating_laundry_full_p10": "0",
        "input_number.heating_kitchen_floor_p10": "0",
    })
    info = info_of(run(states, day(-2.5)))
    assert info["c"] == "0.00"
    states = make_states(laundry="21.5", helpers={"input_number.heating_laundry_full_p10": "0"})
    assert info_of(run(states, day(-2.5)))["c"] == "0.50"
    states = make_states(helpers={"input_number.heating_block_chilly": "0"})
    assert info_of(run(states, day(-2.5)))["m"] == "0.00"
    states = make_states(helpers={"input_number.heating_block_chilly": "unavailable"})
    assert info_of(run(states, day(-2.5)))["m"] == "3.00"


def _without_raw_tomorrow(states):
    states[PRICE_ENTITY] = FakeState("1.5", {})
    return states


def _price_gap():
    prices = fixture_prices()
    del prices[40]
    return make_states(prices=prices)


def _price_none():
    prices = fixture_prices()
    prices[10]["value"] = None
    return make_states(prices=prices)


@pytest.mark.parametrize("label, states, forecast", [
    ("17 entries", make_states(), make_forecast([0.0] * 17)),
    ("no forecast key", make_states(), None),
    ("forecast string", make_states(), "oops"),
    ("laundry unavailable", make_states(laundry="unavailable"), day(0.0)),
    ("kitchen unknown", make_states(kitchen="unknown"), day(0.0)),
    ("kitchen abc", make_states(kitchen="abc"), day(0.0)),
    ("no raw_tomorrow", _without_raw_tomorrow(make_states()), day(0.0)),
    ("price gap", _price_gap(), day(0.0)),
    ("price None", _price_none(), day(0.0)),
])
def test_missing_inputs_write_nothing(label, states, forecast):
    if forecast is None:
        result = run_script(SCRIPT, states, {})
    else:
        result = run(states, forecast)
    assert result.exception is None
    assert result.service_calls == []
    assert result.errors


def test_prices_for_wrong_day():
    yesterday = [
        {"start": e["start"] - dt.timedelta(days=1), "end": e["end"] - dt.timedelta(days=1),
         "value": e["value"]}
        for e in fixture_prices()
    ]
    result = run(make_states(prices=yesterday), day(0.0))
    assert result.exception is None
    assert result.service_calls == []
    assert result.errors


def test_forecast_window():
    # 58 hourly entries from today 14:00 local (13:00 UTC): 10 before tomorrow,
    # 24 inside tomorrow, 24 after.
    temps = [-20.0] * 10 + [-2.5] * 24 + [-20.0] * 24
    forecast = make_forecast(temps, start_utc="2026-11-20T13:00:00+00:00")
    assert len(forecast) == 58
    assert info_of(run(make_states(), forecast))["t"] == "-2.5"


def test_utc_price_datetimes():
    reference = planned(run(make_states(), day(-2.5)))[1]
    utc_prices = [
        {"start": e["start"].astimezone(UTC), "end": e["end"].astimezone(UTC),
         "value": e["value"]}
        for e in fixture_prices()
    ]
    assert planned(run(make_states(prices=utc_prices), day(-2.5)))[1] == reference
    string_prices = [
        {"start": e["start"].isoformat(), "end": e["end"].isoformat(), "value": e["value"]}
        for e in utc_prices
    ]
    assert planned(run(make_states(prices=string_prices), day(-2.5)))[1] == reference


def test_hourly_price_slots():
    first = dt.datetime(2026, 11, 21, tzinfo=LOCAL)
    hourly = [
        {"start": first + dt.timedelta(hours=i), "end": first + dt.timedelta(hours=i + 1),
         "value": 1.0 + i / 10}
        for i in range(24)
    ]
    result = run(make_states(prices=hourly), day(-2.5))
    _, (date, _, info) = planned(result)
    assert date == "2026-11-21"
    # Non-DST values prove the 24 slots were expanded to 96 quarters.
    assert (info["t"], info["m"]) == ("-2.5", "3.00")


def test_dst_day_empty_plan():
    spring = contiguous_quarters(dt.datetime(2027, 3, 28, tzinfo=LOCAL), 92)
    result = run(make_states(prices=spring), day(0.0), now=dt.datetime(2027, 3, 27, 13, 30, tzinfo=LOCAL))
    assert result.exception is None
    assert len(result.service_calls) == 1
    assert result.service_calls[0][2]["value"] == "2027-03-28 |t=na;l=na;k=na;c=na;m=0.00;b=0.00"
    autumn = contiguous_quarters(dt.datetime(2027, 10, 31, tzinfo=LOCAL), 100)
    result = run(make_states(prices=autumn), day(0.0), now=dt.datetime(2027, 10, 30, 13, 30, tzinfo=LOCAL))
    assert result.exception is None
    assert len(result.service_calls) == 1
    assert result.service_calls[0][2]["value"] == "2027-10-31 |t=na;l=na;k=na;c=na;m=0.00;b=0.00"


def test_dst_day_with_gap_is_an_error():
    spring = contiguous_quarters(dt.datetime(2027, 3, 28, tzinfo=LOCAL), 92)
    gapped = spring[:40] + spring[41:]
    result = run(make_states(prices=gapped), day(0.0), now=dt.datetime(2027, 3, 27, 13, 30, tzinfo=LOCAL))
    assert result.exception is None
    assert result.service_calls == []
    assert result.errors


def test_slot_choice():
    plan = "{} |t=0.0;l=22.00;k=22.00;c=1.00;m=3.00;b=6.00"

    def target(slot_a, slot_b):
        result = run(make_states(slot_a=slot_a, slot_b=slot_b), day(-2.5))
        assert result.exception is None
        return result, (result.service_calls[0][2]["entity_id"] if result.service_calls else None)

    a, b = "input_text.heating_plan_a", "input_text.heating_plan_b"
    assert target("", "")[1] == a
    assert target("unknown", "")[1] == a
    assert target("hello", "")[1] == a
    assert target(plan.format("2026-11-20"), "")[1] == b
    assert target(plan.format("2026-11-19"), plan.format("2026-11-20"))[1] == a
    for slot_a, slot_b in [(plan.format("2026-11-21"), ""), ("", plan.format("2026-11-21"))]:
        result, entity = target(slot_a, slot_b)
        assert entity is None
        assert result.errors == []
        assert result.exception is None


def test_write_is_blocking():
    result = run(make_states(), day(-2.5))
    assert result.exception is None
    assert result.service_calls[0][3] is True


# --- Block optimisation --------------------------------------------------

TOMORROW = dt.datetime(2026, 11, 21, tzinfo=LOCAL)


def day_prices(base, spans=()):
    """Tomorrow's 96 quarter entries at `base`, with (start_h, end_h, value) spans."""
    entries = contiguous_quarters(TOMORROW, 96, base)
    for start, end, value in spans:
        for q in range(int(start * 4), int(end * 4)):
            entries[q]["value"] = value
    return entries


def blocks_of(result):
    return planned(result)[1][1]


def to_quarter(text):
    hours, minutes = text.split(":")
    return int(hours) * 4 + int(minutes) // 15


def block_quarters(block):
    start, end = block.split("-")
    return to_quarter(start), to_quarter(end)


THURSDAY_CASES = [
    ("one block", {"helpers": {"input_number.heating_budget_factor": "1.0"}}, day(-2.5),
     ["10:15-12:15", "15:15-16:15"]),
    ("default budget", {}, day(-2.5), ["09:15-12:15", "14:15-17:15"]),
    ("short blocks", {"helpers": {"input_number.heating_block_chilly": "1"}}, day(-2.5),
     ["10:30-11:30", "15:15-16:15"]),
    ("long blocks", {}, day(7.5), ["07:45-11:45", "13:45-19:45"]),
]


def thursday_plan(label):
    """The parsed plan (date, blocks, info) for one of THURSDAY_CASES."""
    for case_label, kwargs, forecast, _ in THURSDAY_CASES:
        if case_label == label:
            result = run(make_states(**kwargs), forecast)
            assert result.exception is None
            return planned(result)[1]
    raise KeyError(label)


def expected_blocks(label):
    return [case[3] for case in THURSDAY_CASES if case[0] == label][0]


def test_thursday_one_block():
    assert thursday_plan("one block")[1] == expected_blocks("one block")


def test_thursday_default_budget():
    assert thursday_plan("default budget")[1] == expected_blocks("default budget")


def test_thursday_short_blocks():
    assert thursday_plan("short blocks")[1] == expected_blocks("short blocks")


def test_thursday_long_blocks():
    _, blocks, info = thursday_plan("long blocks")
    assert (info["m"], info["b"]) == ("6.00", "12.00")
    assert blocks == expected_blocks("long blocks")


@pytest.mark.parametrize("label", [case[0] for case in THURSDAY_CASES])
def test_block_rules(label):
    _, blocks, info = thursday_plan(label)
    assert blocks, "the rules must be checked against a non-empty plan"
    prices = [e["value"] for e in fixture_prices()]
    mean = sum(prices) / len(prices)
    m = round(float(info["m"]) * 4)
    b = round(float(info["b"]) * 4)
    spans = [block_quarters(block) for block in blocks]
    assert sum(end - start for start, end in spans) <= b
    for index, (start, end) in enumerate(spans):
        length = end - start
        assert 4 <= length <= m
        known = prices[end:min(end + 48, 96)]
        reference = (sum(known) + (48 - len(known)) * mean) / 48
        assert sum(prices[start:end]) / length - reference > 0.10
        if index + 1 < len(spans):
            assert spans[index + 1][0] - end >= max(4, -(-length // 2))


def test_flat_day_no_blocks():
    assert blocks_of(run(make_states(prices=day_prices(1.0)), day(-2.5))) == []
    nearly_flat = day_prices(1.0, [(23, 24, 1.05)])
    assert blocks_of(run(make_states(prices=nearly_flat), day(-2.5))) == []


def test_only_the_expensive_part():
    prices = day_prices(0.50, [(0, 2, -0.2), (17, 18, 1.5)])
    assert blocks_of(run(make_states(prices=prices), day(-2.5))) == ["17:00-18:00"]


def test_tie_is_deterministic():
    # Two equal peaks 13 h apart. The dips keep the day mean at 1.0, so the second
    # peak's window (10 h known + 2 h at the day mean) equals the first one's.
    prices = day_prices(1.0, [(0, 1, 2.0), (5, 6, 0.0), (13, 14, 2.0), (18, 19, 0.0)])
    helpers = {"input_number.heating_block_chilly": "1",
               "input_number.heating_budget_factor": "1.0"}
    for _ in range(3):
        result = run(make_states(prices=prices, helpers=helpers), day(-2.5))
        assert blocks_of(result) == ["00:00-01:00"]


MIDNIGHT_PRICES = [(0, 3, 3.0)]
INFO_TAIL = "|t=-2.5;l=22.50;k=22.00;c=1.00;m=3.00;b=6.00"


@pytest.mark.parametrize("today_slot, expected", [
    ("2026-11-20 21:00-24:00" + INFO_TAIL, ["01:30-03:00"]),
    ("2026-11-20 22:30-23:30" + INFO_TAIL, ["00:30-03:00"]),
    ("2026-11-20 08:00-09:00,22:30-23:30" + INFO_TAIL, ["00:30-03:00"]),
    ("2026-11-19 21:00-24:00" + INFO_TAIL, ["00:00-03:00"]),
])
def test_midnight_gap_carried(today_slot, expected):
    states = make_states(prices=day_prices(1.0, MIDNIGHT_PRICES), slot_a=today_slot)
    result = run(states, day(-2.5))
    assert result.exception is None
    assert blocks_of(result) == expected


def test_midnight_gap_carried_from_slot_b():
    states = make_states(prices=day_prices(1.0, MIDNIGHT_PRICES), slot_a="hello",
                         slot_b="2026-11-20 21:00-24:00" + INFO_TAIL)
    entity, (_, blocks, _) = planned(run(states, day(-2.5)))
    assert entity == "input_text.heating_plan_a"
    assert blocks == ["01:30-03:00"]


@pytest.mark.parametrize("today_slot, expected", [
    ("2026-11-20 xx|yy", ["00:00-03:00"]),
    ("2026-11-20 ", ["00:00-03:00"]),
    ("2026-11-20", ["00:00-03:00"]),
    ("2026-11-20 21:00-24:00,|yy", ["01:30-03:00"]),
    ("2026-11-20 21:00-2²:00|yy", ["00:00-03:00"]),
    # The last valid piece is 21:00-24:00; the malformed ones after it are skipped.
    ("2026-11-20 21:00-24:00,25:00-26:00,22:00-21:00,23:10-23:40,ab:cd-ef:gh|yy",
     ["01:30-03:00"]),
])
def test_garbage_slots(today_slot, expected):
    states = make_states(prices=day_prices(1.0, MIDNIGHT_PRICES), slot_a="hello",
                         slot_b=today_slot)
    entity, (_, blocks, _) = planned(run(states, day(-2.5)))
    assert entity == "input_text.heating_plan_a"
    assert blocks == expected


def test_worst_case_runtime():
    helpers = {"input_number.heating_block_warm": "8",
               "input_number.heating_budget_factor": "3"}
    result = run(make_states(helpers=helpers), day(10.0))
    info = info_of(result)
    assert (info["m"], info["b"]) == ("8.00", "24.00")
    assert result.elapsed < 0.5


def test_recovery_spreads_over_twelve_hours():
    """2026-11-22: the evening plateau is blocked, not the cheaper hours after it.

    Valued against the 1.5 h gap after each block the plan was
    01:00-04:00,20:45-23:45: it let the heat pump run through the 1.4-1.57 kr
    plateau and blocked at 1.29 kr once the price fell.
    """
    with open(FIXTURE.parent / "prices_2026-11-22.json", encoding="utf8") as fil:
        raw = json.load(fil)
    prices = [{"start": dt.datetime.fromisoformat(e["start"]),
               "end": dt.datetime.fromisoformat(e["end"]),
               "value": e["value"]} for e in raw]
    helpers = {"input_number.heating_block_cold": "2",
               "input_number.heating_block_chilly": "4",
               "input_number.heating_block_mild": "5",
               "input_number.heating_block_warm": "6"}
    states = make_states(prices=prices, laundry="22.81", kitchen="22.00", helpers=helpers)
    forecast = make_forecast([-1.7] * 24, "2026-11-21T23:00:00+00:00")
    now = dt.datetime(2026, 11, 21, 13, 30, tzinfo=LOCAL)
    tomorrow, blocks, info = planned(run(states, forecast, now))[1]
    assert tomorrow == "2026-11-22"
    assert (info["m"], info["b"]) == ("4.00", "8.25")
    assert blocks == ["15:30-17:30", "18:30-22:30"]
