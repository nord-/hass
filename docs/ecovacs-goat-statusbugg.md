# Ecovacs GOAT — status fastnar på "docked" (deebot-client-fix)

Detta dokument beskriver felsökningen av varför robotgräsklipparen
`lawn_mower.geten` (Ecovacs GOAT O1200 LiDAR Pro) fastnar på tillståndet
`docked` i Home Assistant medan den klipper, samt den fix som postats till
biblioteket `deebot-client`. Spara som referens om maintainers återkopplar på
PR:en.

## Sammanfattning

`ecovacs`-integrationen är push-baserad (`iot_class: cloud_push`) och bygger på
biblioteket `deebot-client`. GOAT-klipparna rapporterar sitt tillstånd via tre
oombedda MQTT-meddelanden, men bara ett av dem hanterades. De andra två
slängdes som `Unknown message`, vilket gjorde att lawn_mower-entiteten aldrig
lämnade `docked` vid schemalagd klippning och aldrig återgick till
`returning`/`docked` efter en körning. Problemet ligger i biblioteket, inte i
HA-konfigurationen — **ingen YAML-workaround hjälper**.

Relaterad uppströms-issue: [home-assistant/core#168621](https://github.com/home-assistant/core/issues/168621).

## Problemet

- `lawn_mower.geten` visade `docked` även mitt under pågående klippning.
- Batteriet (`sensor.geten_batteri`) uppdaterades däremot perfekt.
- Övriga parametrar uppdaterades ~1 gång/dygn (molnets nattsync).
- `homeassistant.update_entity` gjorde ingenting (testat: `last_updated` rörde
  sig inte) — `async_update` → `request_refresh` kör bara `getCleanInfo_V2`,
  som enheten inte svarar på.

## Root cause

Modell-class är `2i0fns` (filen i deebot-client har docstring "GOAT G1" men
class-id:t är O1200 LiDAR Pro). Dess state-capability är
`[GetChargeState(), GetCleanInfoV2()]`. Av debug-loggar (deebot_client på DEBUG,
fw 1.9.16) över en full cykel framgår att GOAT skickar tre tillståndsmeddelanden:

| Meddelande | När | Hanterades? |
|---|---|---|
| `onCleanInfo` | manuell start/paus | ✅ via legacy `get*`-fallback (`getCleanInfo`) |
| `onScheduleTaskInfo` | schemalagd klippning | ❌ `Unknown message` |
| `onChargeInfo` | återgång till dock / klar | ❌ `Unknown message` |

Loggutdrag (avskalat från device-id/koordinater):

```
onChargeInfo       {"trigger":"app","state":"goCharging"}                          -> Unknown message  (borde bli RETURNING)
onChargeInfo       {"trigger":"workComplete","state":"idle"}                        -> Unknown message  (borde bli DOCKED)
onScheduleTaskInfo {"trigger":"continue","state":"clean","cleanState":{"motionState":"working"}} -> Unknown message  (borde bli CLEANING)
onCleanInfo        {"trigger":"app","state":"clean","cleanState":{"motionState":"working"}}       -> StateEvent(CLEANING)  (fungerar)
```

`getChargeInfo` och `getScheduleTaskInfo` saknas i bibliotekets
`_LEGACY_USE_GET_COMMAND`-vitlista och har ingen dedikerad handler, så
meddelandena faller igenom till `Unknown message`. `docked` kommer enbart från
en `getChargeState`-pollning vid återanslutning. Tillståndet avgörs av `state`
(vad enheten gör), inte `trigger` (varför).

## Fixen

Postad som PR **[DeebotUniverse/client.py#1647](https://github.com/DeebotUniverse/client.py/pull/1647)**.

- **`deebot_client/messages/json/charge_state.py`** (ny) — `OnChargeInfo`:
  `state` `goCharging` → `RETURNING`, `idle` → `DOCKED`.
- **`deebot_client/messages/json/clean_info.py`** (ny) — `OnScheduleTaskInfo`
  plus en delad `handle_clean_info()` som håller clean-info → `StateEvent`-parsningen.
- **`deebot_client/commands/json/clean.py`** — `GetCleanInfo` delegerar nu till
  `handle_clean_info()`. Parsningen flyttades från `commands` till `messages`,
  i linje med befintlig importriktning (`commands → messages`); en
  top-level-import åt andra hållet hade blivit cirkulär. Beteendet är oförändrat.
- **`deebot_client/messages/json/__init__.py`** — registrerar de två handlers.

Tillståndsmappning:

| meddelande | `state` | `motionState` | → |
|---|---|---|---|
| onScheduleTaskInfo / onCleanInfo | `clean` | `working` | `CLEANING` |
| onScheduleTaskInfo / onCleanInfo | `clean` | `pause` | `PAUSED` |
| onScheduleTaskInfo / onCleanInfo | `clean` | `goCharging` | `RETURNING` |
| onChargeInfo | `goCharging` | — | `RETURNING` |
| onChargeInfo | `idle` | — | `DOCKED` |

### PR-detaljer

- **Fork/gren:** `nord-/client.py`, gren `feat/mower-state-charge-schedule-push`
- **Bas:** `dev` · **Diff:** +249 / −39 över 6 filer
- Conventional commit, LF, ingen AI-attribution, `@pytest.mark.benchmark` på
  testfunktionerna enligt repots konvention.

## Verifiering

- 15 nya tester gröna (`tests/messages/json/test_charge_state.py`,
  `test_clean_info.py`), `test_GetCleanInfo` oförändrad och grön
  (refaktoreringen är beteendebevarande).
- `ruff check` + `ruff format --check` rena.
- Routning verifierad: `get_message("onChargeInfo"/"onScheduleTaskInfo")` löser
  nu till de nya handlers; ingen cirkulär import.
- Lokalt byggdes inte Rust-komponenten (ingen toolchain på Windows). De tre
  Rust-symbolerna (`rs.map.RotationAngle`/`PositionType`, `rs.util.decompress_base64_data`)
  stubbades i en runner, och `conftest` kringgicks med `--noconftest`. Repots CI
  bygger Rust på riktigt.

## Relaterade uppströms-PR:er (komplementära, ej konkurrerande)

- **#1641** (GOAT A3000) — inför `OnCleanInfo`/`OnPos`/`OnMI`/`OnArI`. Vår PR rör
  **inte** `onCleanInfo` och täcker bara de två meddelanden ingen annan PR tar.
- **#1624** (`CleanMower`) — startkommandot (den separata "kan inte starta via
  HA"-buggen). Vår PR är tillståndsläsningen.
- **#1625 / #1626 / #1627** (monsivar) — O1200-profil + zonstyrning.
- Core-PR:erna #170229 (RTK-sensorer) och #170222 (`raw_get_positions` för
  mowers) är orelaterade till tillståndet.

## Om en maintainer återkopplar

Tre punkter kom upp i intern granskning (alla under blockeringsgräns):

1. **Funktion vs klassarv** — övriga `commands` återanvänder `messages` via
   arv (t.ex. `GetBattery(OnBattery)`). Vi använder en delad funktion eftersom
   `GetCleanInfo` måste behålla sin command-basklass. Nämnt som medvetet val i
   PR-beskrivningen; kan struktureras om till klassbaserad form om de vill.
2. **`idle → DOCKED`** för `onChargeInfo` — tolkning utifrån att `idle` kom med
   `trigger:workComplete` direkt efter `goCharging`, dvs. åter i dock. Motiverat
   i kodkommentar. Kan justeras om maintainer har annan vy.
3. **Konsolidering med #1641** — om #1641 mergas först kan den delade
   clean-info-parsningen behöva samordnas. PR-beskrivningen erbjuder rebase.

### Köra testerna lokalt igen

Klona forken, stubba Rust och kör bara de berörda testerna (kringgå `conftest`
som drar in `aiomqtt`):

```python
# run_fork.py — stubbar rs.* och kör pytest mot forken
import os, sys, types
REPO = "<sökväg till client.py-klon>"
os.chdir(REPO); sys.path.insert(0, REPO)
m = types.ModuleType("deebot_client.rs.map")
m.RotationAngle = type("RotationAngle", (), {}); m.PositionType = type("PositionType", (), {})
u = types.ModuleType("deebot_client.rs.util"); u.decompress_base64_data = lambda *a, **k: b""
p = types.ModuleType("deebot_client.rs"); p.__path__ = []
sys.modules.update({"deebot_client.rs": p, "deebot_client.rs.map": m, "deebot_client.rs.util": u})
import pytest
raise SystemExit(pytest.main([
    "tests/messages/json/test_charge_state.py",
    "tests/messages/json/test_clean_info.py",
    "tests/commands/json/test_clean.py::test_GetCleanInfo",
    "--noconftest", "-q",
]))
```

Kräver `pip install pytest testfixtures ruff`.

## Status för HA-konfigurationen

Ingen ändring kvar i detta repo. En tidigare testad `update_entity`-automation
togs bort eftersom den bevisligen inte gör något. När #1647 mergas kommer en ny
`deebot-client`-release, varefter Home Assistant bumpar dependensen och fixen
når installationen automatiskt. Tills dess syns `mowing` endast vid manuell
start via Ecovacs-appen, inte vid schemalagd klippning.
