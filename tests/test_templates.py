"""Tests for the template sensors in the packages, rendered with plain jinja2."""
from datetime import datetime, timedelta
from pathlib import Path

import jinja2
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


class _HaLoader(yaml.SafeLoader):
    """Safe loader that tolerates Home Assistant tags such as !secret and !include."""


def _any_tag(loader, suffix, node):
    return f"<{suffix}>"


_HaLoader.add_multi_constructor("!", _any_tag)


def load_yaml(relative_path: str):
    with open(ROOT / relative_path, encoding="utf-8") as f:
        return yaml.load(f, Loader=_HaLoader)


def render(template: str, states: dict, now: datetime) -> str:
    """Render an HA-style template with stubs for states(), is_state(), now() and friends."""
    env = jinja2.Environment()

    def _states(entity_id):
        return states.get(entity_id, "unknown")

    def _float(value, default=None):
        try:
            return float(value)
        except (TypeError, ValueError):
            if default is None:
                raise
            return default

    env.globals.update(
        states=_states,
        is_state=lambda entity_id, state: _states(entity_id) == state,
        now=lambda: now,
        timedelta=timedelta,
        float=_float,
    )
    env.filters["float"] = _float
    return env.from_string(template).render().strip()


def _binary_sensor_state_template() -> str:
    package = load_yaml("packages/heating.yaml")
    for group in package["template"]:
        for binary in group.get("binary_sensor", []):
            if binary["unique_id"] == "varmepump_blockerad_enligt_plan":
                return binary["state"]
    raise AssertionError("binary sensor not found")


NOW = datetime(2026, 11, 20, 13, 30)
TAIL = "|t=-1.0;l=0.50;k=0.50;c=0.50;m=3.00;b=6.00"


def blocked(plan_a, plan_b="", now=NOW, enabled="on"):
    states = {
        "input_boolean.heating_plan_enabled": enabled,
        "input_text.heating_plan_a": plan_a,
        "input_text.heating_plan_b": plan_b,
    }
    return render(_binary_sensor_state_template(), states, now) == "True"


def plan(blocks, date="2026-11-20"):
    return f"{date} {blocks}{TAIL}"


def test_inside_slot():
    assert blocked(plan("13:00-14:00"))


def test_end_is_exclusive():
    assert not blocked(plan("12:00-13:30"))


def test_start_is_inclusive():
    assert blocked(plan("13:30-24:00"))


def test_end_of_day():
    assert blocked(plan("22:00-24:00"), now=datetime(2026, 11, 20, 23, 59))


def test_empty_block_list():
    assert not blocked(plan(""))


@pytest.mark.parametrize("date", ["2026-11-19", "2026-11-21"])
def test_other_day_is_ignored(date):
    assert not blocked(plan("13:00-14:00", date))


@pytest.mark.parametrize("garbage", ["unknown", "", "hello", "unavailable"])
def test_garbage_is_no_plan(garbage):
    assert not blocked(garbage)


def test_malformed_piece_skipped():
    assert blocked(plan("xx,13:00-14:00"))


def test_uses_slot_b_when_a_is_tomorrow():
    assert blocked(plan("13:00-14:00", "2026-11-21"), plan("13:00-14:00"))


def test_slot_b_decides_when_a_is_tomorrow():
    assert not blocked(plan("13:00-14:00", "2026-11-21"), plan("15:00-16:00"))


def test_master_switch_off():
    assert not blocked(plan("13:00-14:00"), enabled="off")


# --- Dashboard card (lovelace_manual.yaml) ---


def _find_cards(node, title):
    if isinstance(node, dict):
        if node.get("title") == title:
            yield node
        for value in node.values():
            yield from _find_cards(value, title)
    elif isinstance(node, list):
        for value in node:
            yield from _find_cards(value, title)


def _card(title):
    cards = list(_find_cards(load_yaml("lovelace_manual.yaml"), title))
    assert len(cards) == 1
    return cards[0]


def card_text(plan_a="", plan_b="", now=NOW):
    states = {
        "input_text.heating_plan_a": plan_a,
        "input_text.heating_plan_b": plan_b,
    }
    return render(_card("Värmeplan")["content"], states, now)


def test_card_shows_today_and_tomorrow():
    text = card_text(plan("08:00-11:00"), plan("06:00-09:00", "2026-11-21"))
    assert "Idag" in text and "08:00-11:00" in text
    assert "Imorgon" in text and "06:00-09:00" in text
    assert "Ingen plan" not in text


def test_card_info_line():
    text = card_text(plan("08:00-11:00"))
    assert "Kallaste 6 h: -1.0°" in text
    assert "Tvättstuga p10 0.50°" in text
    assert "Kök p10 0.50°" in text
    assert "Justering 50 %" in text
    assert "Max block 3.00 h" in text
    assert "Budget 6.00 h" in text


def test_card_no_tomorrow_after_15():
    text = card_text(plan("08:00-11:00"), now=datetime(2026, 11, 20, 16, 0))
    assert "Ingen plan för imorgon" in text


def test_card_no_tomorrow_before_15_is_quiet():
    text = card_text(plan("08:00-11:00"), now=datetime(2026, 11, 20, 12, 0))
    assert "Ingen plan för imorgon" not in text


def test_card_no_today():
    text = card_text(plan("08:00-11:00", "2026-11-19"))
    assert "Ingen plan för idag" in text


def test_card_empty_blocks():
    assert "Inga block" in card_text(plan(""))


def test_card_na_fields_show_dash():
    text = card_text("2026-11-20 |t=na;l=na;k=na;c=na;m=0.00;b=0.00")
    assert "Kallaste 6 h: – · Tvättstuga p10 – · Kök p10 –" in text
    assert "Justering – %" in text
    assert "Inga block" in text


def test_card_garbage_slot_is_no_plan():
    assert "Ingen plan för idag" in card_text("hello", "unknown")


def test_settings_card_lists_entities():
    entities = _card("Värmeplan, inställningar")["entities"]
    ids = {e["entity"] if isinstance(e, dict) else e for e in entities}
    assert "input_boolean.heating_plan_enabled" in ids
    assert {f"input_number.heating_block_{n}" for n in ("cold", "chilly", "mild", "warm")} <= ids
    assert {
        "input_number.heating_budget_factor",
        "input_number.heating_laundry_full_p10",
        "input_number.heating_kitchen_floor_p10",
        "sensor.tvattstugan_p10_24h",
        "sensor.koket_p10_24h",
    } <= ids


def test_card_no_line_starts_with_space():
    cases = [
        card_text("", "", now=datetime(2026, 11, 20, 16, 0)),
        card_text(plan("08:00-11:00"), plan("06:00-09:00", "2026-11-21")),
    ]
    for text in cases:
        for line in text.split("\n"):
            assert not line.startswith(" "), repr(text)
