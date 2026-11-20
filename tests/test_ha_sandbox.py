"""Tests for the local mirror of the HA python_script sandbox."""

from ha_sandbox import FakeState, run_script


def run(tmp_path, source, states=None, data=None, now=None):
    path = tmp_path / "script.py"
    path.write_text(source, encoding="utf8")
    return run_script(str(path), states or {}, data, now)


def test_runs_plain_script(tmp_path):
    result = run(
        tmp_path,
        'hass.services.call("input_text", "set_value", '
        '{"entity_id": "input_text.x", "value": "v"}, True)\n',
    )
    assert result.service_calls == [
        ("input_text", "set_value", {"entity_id": "input_text.x", "value": "v"}, True)
    ]
    assert result.exception is None


def test_rejects_subscript_augassign(tmp_path):
    result = run(tmp_path, 'd = {"a": 1}\nd["a"] += 1\n')
    assert result.compile_errors


def test_rejects_import(tmp_path):
    result = run(tmp_path, "import os\n")
    assert result.compile_errors or result.exception is not None


def test_rejects_star_args(tmp_path):
    result = run(tmp_path, "f = max\nf(*[1])\n")
    assert result.compile_errors or result.exception is not None


def test_rejects_range_1000(tmp_path):
    result = run(tmp_path, "x = range(1000)\n")
    assert result.compile_errors or result.exception is not None


def test_rejects_disallowed_dt_util(tmp_path):
    result = run(tmp_path, "dt_util.set_default_time_zone\n")
    assert result.exception is not None


def test_reads_state_and_now(tmp_path):
    result = run(
        tmp_path,
        'output["s"] = hass.states.get("sensor.a").state\n'
        'output["h"] = dt_util.now().hour\n',
        states={"sensor.a": FakeState("1.5")},
    )
    assert result.exception is None
    assert result.output == {"s": "1.5", "h": 13}


def test_dt_util_semantics(tmp_path):
    src = (
        'output["bad"] = dt_util.parse_datetime("garbage") is None\n'
        'output["naive"] = dt_util.as_local(datetime.datetime(2026, 7, 1, 12, 0)).isoformat()\n'
        # datetime.timezone is not allowed in the sandbox, so build the UTC value
        # with dt_util.utc_from_timestamp (2026-07-01 12:00 UTC).
        'output["utc"] = dt_util.as_local(dt_util.utc_from_timestamp(1782907200)).isoformat()\n'
        'output["sod"] = dt_util.start_of_local_day().isoformat()\n'
    )
    result = run(tmp_path, src)
    assert result.exception is None
    assert result.output == {
        "bad": True,
        "naive": "2026-07-01T12:00:00+02:00",
        "utc": "2026-07-01T14:00:00+02:00",
        "sod": "2026-11-20T00:00:00+01:00",
    }


def test_logger_error_captured(tmp_path):
    result = run(tmp_path, 'logger.error("boom")\nlogger.info("ignored")\n')
    assert result.errors == ["boom"]


def test_exception_captured(tmp_path):
    result = run(tmp_path, 'float("x")\n')
    assert isinstance(result.exception, ValueError)
    assert result.errors == []
