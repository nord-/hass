"""Local mirror of the Home Assistant ``python_script`` sandbox.

Provenance: the allowlists, ``IOPERATOR_TO_OPERATOR``, ``guarded_import``,
``guarded_inplacevar``, ``StubPrinter``, ``TimeWrapper`` and the body of
``execute()`` are copied from
``homeassistant/components/python_script/helpers.py`` at Home Assistant core
tag 2026.11.2 (RestrictedPython==8.5, see tests/requirements.txt). The real
``hass`` and ``dt_util`` objects are replaced by fakes, and ``logger`` /
exception handling are adapted so tests can inspect them.
"""

import datetime as dt
import operator
import time
import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Number
from typing import Any
from zoneinfo import ZoneInfo

from RestrictedPython import (
    compile_restricted_exec,
    limited_builtins,
    safe_builtins,
    utility_builtins,
)
from RestrictedPython.Eval import default_guarded_getitem
from RestrictedPython.Guards import (
    full_write_guard,
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
)

LOCAL_TZ = ZoneInfo("Europe/Stockholm")
DEFAULT_NOW = dt.datetime(2026, 11, 20, 13, 30, tzinfo=LOCAL_TZ)

ALLOWED_HASS = {"bus", "services", "states"}
ALLOWED_EVENTBUS = {"fire"}
ALLOWED_STATEMACHINE = {
    "entity_ids",
    "all",
    "get",
    "is_state",
    "is_state_attr",
    "remove",
    "set",
}
ALLOWED_SERVICEREGISTRY = {"services", "has_service", "call"}
ALLOWED_TIME = {
    "sleep",
    "strftime",
    "strptime",
    "gmtime",
    "localtime",
    "ctime",
    "time",
    "mktime",
}
ALLOWED_DATETIME = {"date", "time", "datetime", "timedelta", "tzinfo"}
ALLOWED_DT_UTIL = {
    "utcnow",
    "now",
    "as_utc",
    "as_timestamp",
    "as_local",
    "utc_from_timestamp",
    "start_of_local_day",
    "parse_datetime",
    "parse_date",
    "get_age",
}


class ScriptError(Exception):
    """When a script error occurs (stand-in for HA's ScriptError)."""


IOPERATOR_TO_OPERATOR = {
    "%=": operator.mod,
    "&=": operator.and_,
    "**=": operator.pow,
    "*=": operator.mul,
    "+=": operator.add,
    "-=": operator.sub,
    "//=": operator.floordiv,
    "/=": operator.truediv,
    "<<=": operator.lshift,
    ">>=": operator.rshift,
    "@=": operator.matmul,
    "^=": operator.xor,
    "|=": operator.or_,
}


def guarded_import(
    name: str,
    globals: Mapping[str, object] | None = None,
    locals: Mapping[str, object] | None = None,
    fromlist: Sequence[str] = (),
    level: int = 0,
) -> types.ModuleType:
    """Guard imports."""
    # Allow import of _strptime needed by datetime.datetime.strptime
    if name == "_strptime":
        return __import__(name, globals, locals, fromlist, level)
    raise ImportError(f"Not allowed to import {name}")


def guarded_inplacevar(op: str, target: Any, operand: Any) -> Any:
    """Implement augmented-assign (+=, -=, etc.) operators for restricted code."""
    if not isinstance(target, (list, Number, str)):
        raise ScriptError(f"The {op!r} operation is not allowed on a {type(target)}")
    op_fun = IOPERATOR_TO_OPERATOR.get(op)
    if not op_fun:
        raise ScriptError(f"The {op!r} operation is not allowed")
    return op_fun(target, operand)


class StubPrinter:
    """Class to handle printing inside scripts."""

    def __init__(self, _getattr_: Callable) -> None:
        """Initialize our printer."""

    def _call_print(self, *objects: object, **kwargs: Any) -> None:
        """Print text (ignored, as in HA)."""


class TimeWrapper:
    """Wrap the time module."""

    def sleep(self, *args: Any, **kwargs: Any) -> None:
        """Sleep method."""
        time.sleep(*args, **kwargs)

    def __getattr__(self, attr: str) -> Any:
        """Fetch an attribute from Time module."""
        attribute = getattr(time, attr)
        if callable(attribute):

            def wrapper(*args: Any, **kw: Any) -> Any:
                """Wrap to return callable method if callable."""
                return attribute(*args, **kw)

            return wrapper
        return attribute


# --- Fakes -----------------------------------------------------------------


class FakeState:
    """Minimal stand-in for homeassistant.core.State."""

    def __init__(self, state: str, attributes: dict | None = None) -> None:
        self.state = state
        self.attributes = attributes or {}


class FakeStates:
    """Fake state machine."""

    def __init__(self, states: dict[str, FakeState]) -> None:
        self._states = dict(states)

    def get(self, entity_id: str) -> FakeState | None:
        return self._states.get(entity_id)

    def set(self, entity_id: str, new_state: Any, attributes: dict | None = None,
            force_update: bool = False) -> None:
        self._states[entity_id] = FakeState(str(new_state), attributes)

    def entity_ids(self, domain_filter: str | None = None) -> list[str]:
        return [
            e for e in self._states
            if domain_filter is None or e.split(".")[0] == domain_filter
        ]

    def all(self, domain_filter: str | None = None) -> list[FakeState]:
        return [self._states[e] for e in self.entity_ids(domain_filter)]

    def is_state(self, entity_id: str, state: str) -> bool:
        current = self._states.get(entity_id)
        return current is not None and current.state == state

    def is_state_attr(self, entity_id: str, name: str, value: Any) -> bool:
        current = self._states.get(entity_id)
        return current is not None and current.attributes.get(name) == value

    def remove(self, entity_id: str) -> bool:
        return self._states.pop(entity_id, None) is not None


class FakeServices:
    """Fake service registry that records calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, bool]] = []

    def call(self, domain: str, service: str, data: dict | None = None,
             blocking: bool = False) -> None:
        self.calls.append((domain, service, data, blocking))

    def has_service(self, domain: str, service: str) -> bool:
        return True

    def services(self) -> dict:
        return {}


class FakeBus:
    """Fake event bus."""

    def fire(self, event_type: str, event_data: dict | None = None) -> None:
        """Ignore fired events."""


class FakeHass:
    """Fake HomeAssistant object exposing bus, services and states."""

    def __init__(self, states: dict[str, FakeState]) -> None:
        self.states = FakeStates(states)
        self.services = FakeServices()
        self.bus = FakeBus()


class FakeDtUtil:
    """Mirror of homeassistant.util.dt on Europe/Stockholm with a fixed now."""

    def __init__(self, now: dt.datetime) -> None:
        self._now = now.astimezone(LOCAL_TZ) if now.tzinfo else now.replace(tzinfo=LOCAL_TZ)

    def utcnow(self) -> dt.datetime:
        return self._now.astimezone(dt.timezone.utc)

    def now(self, time_zone: dt.tzinfo | None = None) -> dt.datetime:
        return self._now.astimezone(time_zone or LOCAL_TZ)

    def as_utc(self, dattim: dt.datetime) -> dt.datetime:
        if dattim.tzinfo == dt.timezone.utc:
            return dattim
        if dattim.tzinfo is None:
            dattim = dattim.replace(tzinfo=LOCAL_TZ)
        return dattim.astimezone(dt.timezone.utc)

    def as_timestamp(self, dt_value: dt.datetime | str) -> float:
        if hasattr(dt_value, "timestamp"):
            parsed = dt_value
        else:
            parsed = self.parse_datetime(str(dt_value))
            if parsed is None:
                raise ValueError(f"Could not parse date {dt_value}")
        return self.as_utc(parsed).timestamp()

    def as_local(self, dattim: dt.datetime) -> dt.datetime:
        if dattim.tzinfo == LOCAL_TZ:
            return dattim
        if dattim.tzinfo is None:
            dattim = dattim.replace(tzinfo=LOCAL_TZ)
        return dattim.astimezone(LOCAL_TZ)

    def utc_from_timestamp(self, timestamp: float) -> dt.datetime:
        return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)

    def start_of_local_day(self, dt_or_d: dt.date | dt.datetime | None = None) -> dt.datetime:
        if dt_or_d is None:
            date = self.now().date()
        elif isinstance(dt_or_d, dt.datetime):
            date = dt_or_d.date()
        else:
            date = dt_or_d
        return dt.datetime.combine(date, dt.time(), tzinfo=LOCAL_TZ)

    def parse_datetime(self, dt_str: str, *, raise_on_error: bool = False) -> dt.datetime | None:
        try:
            return dt.datetime.fromisoformat(dt_str)
        except ValueError:
            if raise_on_error:
                raise
            return None

    def parse_date(self, dt_str: str) -> dt.date | None:
        try:
            return dt.date.fromisoformat(dt_str)
        except ValueError:
            return None

    def get_age(self, date: dt.datetime) -> str:
        """Return a human-readable age such as '3 hours' (HA's algorithm)."""
        def formatn(number: int, unit: str) -> str:
            return f"{number} {unit}{'' if number == 1 else 's'}"

        delta = (self.now() - date).total_seconds()
        rounded_delta = round(delta)
        units = ["second", "minute", "hour", "day", "month"]
        factors = [60, 60, 24, 30, 12]
        selected_unit = "year"
        for i, next_factor in enumerate(factors):
            if rounded_delta < next_factor:
                selected_unit = units[i]
                break
            delta /= next_factor
            rounded_delta = round(delta)
        return formatn(rounded_delta, selected_unit)


class StubLogger:
    """Script logger: records ``error`` messages, ignores other levels."""

    def __init__(self, errors: list[str]) -> None:
        self._errors = errors

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._errors.append(msg % args if args else msg)

    def _ignore(self, *args: Any, **kwargs: Any) -> None:
        """Ignore a log call."""

    debug = info = warning = critical = exception = _ignore


@dataclass
class SandboxResult:
    """Outcome of running a script in the sandbox."""

    service_calls: list[tuple[str, str, dict, bool]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    exception: BaseException | None = None
    compile_errors: list[str] = field(default_factory=list)
    output: dict = field(default_factory=dict)
    elapsed: float = 0.0


def run_script(
    path: str,
    states: dict[str, FakeState],
    data: dict | None = None,
    now: dt.datetime | None = None,
) -> SandboxResult:
    """Run the script at ``path`` the way HA's python_script would."""
    result = SandboxResult()
    with open(path, encoding="utf8") as fil:
        source = fil.read()
    filename = path

    compiled = compile_restricted_exec(source, filename=filename)
    if compiled.errors:
        result.compile_errors = list(compiled.errors)
        return result

    hass = FakeHass(states)
    dt_util = FakeDtUtil(now or DEFAULT_NOW)
    result.service_calls = hass.services.calls

    def protected_getattr(obj: object, name: str, default: Any = None) -> Any:
        """Restricted method to get attributes."""
        if name.startswith("async_"):
            raise ScriptError("Not allowed to access async methods")
        if (
            (obj is hass and name not in ALLOWED_HASS)
            or (obj is hass.bus and name not in ALLOWED_EVENTBUS)
            or (obj is hass.states and name not in ALLOWED_STATEMACHINE)
            or (obj is hass.services and name not in ALLOWED_SERVICEREGISTRY)
            or (obj is dt_util and name not in ALLOWED_DT_UTIL)
            or (obj is dt and name not in ALLOWED_DATETIME)
            or (isinstance(obj, TimeWrapper) and name not in ALLOWED_TIME)
        ):
            raise ScriptError(f"Not allowed to access {obj.__class__.__name__}.{name}")

        return getattr(obj, name, default)

    extra_builtins = {
        "__import__": guarded_import,
        "datetime": dt,
        "sorted": sorted,
        "time": TimeWrapper(),
        "dt_util": dt_util,
        "min": min,
        "max": max,
        "sum": sum,
        "any": any,
        "all": all,
        "enumerate": enumerate,
    }
    builtins = safe_builtins.copy()
    builtins.update(utility_builtins)
    builtins.update(limited_builtins)
    builtins.update(extra_builtins)
    restricted_globals = {
        "__builtins__": builtins,
        "_print_": StubPrinter,
        "_getattr_": protected_getattr,
        "_write_": full_write_guard,
        "_getiter_": iter,
        "_getitem_": default_guarded_getitem,
        "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
        "_unpack_sequence_": guarded_unpack_sequence,
        "_inplacevar_": guarded_inplacevar,
        "hass": hass,
        "data": data or {},
        "logger": StubLogger(result.errors),
        "output": {},
    }

    started = time.perf_counter()
    try:
        exec(compiled.code, restricted_globals)  # noqa: S102
        if not isinstance(restricted_globals["output"], dict):
            raise ScriptError("Expected `output` to be a dictionary")
    except Exception as err:  # HA swallows and logs these
        result.exception = err
    result.elapsed = time.perf_counter() - started
    result.output = restricted_globals["output"] if isinstance(
        restricted_globals["output"], dict) else {}
    return result
