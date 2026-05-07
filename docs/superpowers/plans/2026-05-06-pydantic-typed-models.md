# Pydantic Typed Models + Dynamic Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all `dict[str, Any]` device access with Pydantic v2 models validated at the API boundary, and add dynamic device discovery so new thermostats appear within one poll interval.

**Architecture:** A new `models.py` defines the full `WattsDevice` model hierarchy. `api.py` validates each device at the boundary, skipping invalid ones. `coordinator.py` stores data as `dict[str, WattsDevice]` for O(1) lookup. Climate and sensor entities switch to typed attribute access and register a coordinator listener that adds new entities on each poll.

**Tech Stack:** Python 3.12, Pydantic v2 (bundled with Home Assistant — no `manifest.json` change needed), pytest.

---

## File map

| File | Action |
|---|---|
| `custom_components/watts_home/models.py` | **Create** — all Pydantic models |
| `tests/test_models.py` | **Create** — model validation tests |
| `custom_components/watts_home/api.py` | **Modify** — `get_devices()` return type + per-item parse |
| `custom_components/watts_home/coordinator.py` | **Modify** — type param + `_async_update_data` |
| `tests/test_climate.py` | **Modify** — fixtures use `WattsDevice`; module pre-load order |
| `custom_components/watts_home/climate.py` | **Modify** — helper signatures, entity constructor, discovery |
| `tests/test_sensor.py` | **Modify** — fixtures use `WattsDevice` |
| `custom_components/watts_home/sensor.py` | **Modify** — entity constructors, `_device()`, discovery |

---

## Task 1: Create `models.py` and `tests/test_models.py`

**Files:**
- Create: `custom_components/watts_home/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_models.py`:

```python
"""Tests for Pydantic models in models.py."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.watts_home.models import WattsDevice

_FIXTURE = Path(__file__).parent / "fixtures" / "devices.json"


def _raw_devices() -> list[dict]:
    return json.loads(_FIXTURE.read_text())["body"]


def test_model_validate_all_devices() -> None:
    raw = _raw_devices()
    devices = [WattsDevice.model_validate(d) for d in raw]
    assert len(devices) == len(raw)
    for device in devices:
        assert isinstance(device.device_id, str)
        assert isinstance(device.name, str)
        assert isinstance(device.model_number, str)
        assert isinstance(device.is_connected, bool)


def test_extra_fields_are_ignored() -> None:
    WattsDevice.model_validate({
        "deviceId": "test-id",
        "name": "Test",
        "modelNumber": "561",
        "isConnected": True,
        "data": None,
        "unknownFutureField": "some_value",
        "imageUrl": "https://example.com/img.png",
    })


def test_null_data_parses_without_error() -> None:
    device = WattsDevice.model_validate({
        "deviceId": "test-id",
        "name": "Test",
        "modelNumber": "561",
        "isConnected": False,
        "data": None,
    })
    assert device.data is None


def test_null_data_subfields_parse_without_error() -> None:
    device = WattsDevice.model_validate({
        "deviceId": "test-id",
        "name": "Test",
        "modelNumber": "561",
        "isConnected": False,
        "data": {
            "Mode": None,
            "State": None,
            "Sensors": None,
            "Target": None,
            "TempUnits": None,
            "SchedEnable": None,
            "Fan": None,
        },
    })
    assert device.data is not None
    assert device.data.mode is None
    assert device.data.sensors is None
    assert device.data.state is None
    assert device.data.target is None


def test_full_device_fields_round_trip() -> None:
    """A device with every sub-field present parses to the right values."""
    device = WattsDevice.model_validate({
        "deviceId": "abc-123",
        "name": "Hallway",
        "modelNumber": "562",
        "isConnected": True,
        "data": {
            "Mode": {"Val": "Heat", "Enum": ["Heat", "Cool", "Auto", "Off"]},
            "State": {"Op": "Heat"},
            "Sensors": {
                "Room": {"Val": 71.5, "Status": "Okay"},
                "Floor": {"Val": 0.0, "Status": "NotInstalled"},
                "Outdoor": {"Val": 45.0, "Status": "Okay"},
                "RH": {"Val": 42.0, "Status": "Okay"},
            },
            "Target": {"Heat": 70.0, "Cool": 78.0, "Min": 40.0, "Max": 95.0, "Steps": 1.0},
            "TempUnits": {"Val": "F"},
            "SchedEnable": {"Val": "Off"},
            "Fan": {"Val": "Auto", "Enum": ["Auto", "On"]},
        },
    })
    assert device.device_id == "abc-123"
    assert device.data is not None
    assert device.data.mode is not None
    assert device.data.mode.val == "Heat"
    assert device.data.mode.enum == ["Heat", "Cool", "Auto", "Off"]
    assert device.data.state is not None
    assert device.data.state.op == "Heat"
    assert device.data.sensors is not None
    assert device.data.sensors.room is not None
    assert device.data.sensors.room.val == 71.5
    assert device.data.sensors.room.status == "Okay"
    assert device.data.sensors.outdoor is not None
    assert device.data.sensors.outdoor.status == "Okay"
    assert device.data.sensors.rh is not None
    assert device.data.sensors.rh.val == 42.0
    assert device.data.target is not None
    assert device.data.target.heat == 70.0
    assert device.data.target.cool == 78.0
    assert device.data.target.min == 40.0
    assert device.data.target.max == 95.0
    assert device.data.target.steps == 1.0
    assert device.data.temp_units is not None
    assert device.data.temp_units.val == "F"
    assert device.data.fan is not None
    assert device.data.fan.val == "Auto"
    assert device.data.fan.enum == ["Auto", "On"]
    assert device.data.sched_enable is not None
    assert device.data.sched_enable.val == "Off"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'custom_components.watts_home.models'`

- [ ] **Step 3: Create `models.py`**

Create `custom_components/watts_home/models.py`:

```python
"""Pydantic v2 models for Watts Home API device responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WattsSensor(BaseModel):
    val: float = Field(alias="Val")
    status: str = Field(alias="Status")


class WattsSensors(BaseModel):
    room: WattsSensor | None = Field(None, alias="Room")
    floor: WattsSensor | None = Field(None, alias="Floor")
    outdoor: WattsSensor | None = Field(None, alias="Outdoor")
    rh: WattsSensor | None = Field(None, alias="RH")


class WattsState(BaseModel):
    op: str = Field(alias="Op")


class WattsMode(BaseModel):
    val: str = Field(alias="Val")
    enum: list[str] = Field(alias="Enum")


class WattsTarget(BaseModel):
    heat: float | None = Field(None, alias="Heat")
    cool: float | None = Field(None, alias="Cool")
    min: float = Field(alias="Min")
    max: float = Field(alias="Max")
    steps: float = Field(alias="Steps")


class WattsTempUnits(BaseModel):
    val: str = Field(alias="Val")


class WattsFan(BaseModel):
    val: str = Field(alias="Val")
    enum: list[str] = Field(alias="Enum")


class WattsSchedEnable(BaseModel):
    val: str = Field(alias="Val")


class WattsDeviceData(BaseModel):
    sensors: WattsSensors | None = Field(None, alias="Sensors")
    state: WattsState | None = Field(None, alias="State")
    mode: WattsMode | None = Field(None, alias="Mode")
    target: WattsTarget | None = Field(None, alias="Target")
    temp_units: WattsTempUnits | None = Field(None, alias="TempUnits")
    sched_enable: WattsSchedEnable | None = Field(None, alias="SchedEnable")
    fan: WattsFan | None = Field(None, alias="Fan")


class WattsDevice(BaseModel):
    device_id: str = Field(alias="deviceId")
    name: str
    model_number: str = Field(alias="modelNumber")
    is_connected: bool = Field(alias="isConnected")
    data: WattsDeviceData | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_models.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/watts_home/models.py tests/test_models.py
git commit -m "feat: add Pydantic v2 models for Watts API device responses"
```

---

## Task 2: Update `api.py` — typed `get_devices()`

**Files:**
- Modify: `custom_components/watts_home/api.py`

- [ ] **Step 1: Update `get_devices()` in `api.py`**

Replace the `get_devices` method (lines 76–80) and add the necessary imports.

At the top of `api.py`, add to the imports block:

```python
from pydantic import ValidationError

from .models import WattsDevice
```

Replace the `get_devices` method:

```python
async def get_devices(self, location_id: str) -> list[WattsDevice]:
    raw: list[dict] = await self._get(f"/Location/{location_id}/Devices")
    devices: list[WattsDevice] = []
    for item in raw:
        try:
            devices.append(WattsDevice.model_validate(item))
        except ValidationError as exc:
            _LOGGER.error(
                "Device %s failed Pydantic validation, marking unavailable: %s",
                item.get("deviceId"),
                exc,
            )
    return devices
```

Also remove `from typing import Any` if it's no longer used elsewhere in `api.py`. It is still used in `set_temperature` and `_patch`, so keep it.

- [ ] **Step 2: Run all tests**

```bash
.venv/bin/pytest tests/ -v
```

Expected: `test_models.py` still passes; `test_climate.py` and `test_sensor.py` still pass (they don't call `api.py` directly).

- [ ] **Step 3: Commit**

```bash
git add custom_components/watts_home/api.py
git commit -m "feat: validate devices with Pydantic at API boundary in get_devices()"
```

---

## Task 3: Update `coordinator.py` — dict-keyed data

**Files:**
- Modify: `custom_components/watts_home/coordinator.py`

- [ ] **Step 1: Update `coordinator.py`**

Add the import for `WattsDevice`:

```python
from .models import WattsDevice
```

Change the class declaration (line 28):

```python
class WattsDataUpdateCoordinator(DataUpdateCoordinator[dict[str, WattsDevice]]):
```

Change `_async_update_data` return type and final lines (lines 89–101):

```python
async def _async_update_data(self) -> dict[str, WattsDevice]:
    try:
        access_token = await self._ensure_token()
        client = WattsApiClient(self._session, access_token)
        locations = await client.get_locations()
        location = WattsApiClient.find_default_location(locations)
        self.location_id = str(location["locationId"])
        _LOGGER.debug(
            "Polling location %s (%s)", location.get("name"), self.location_id
        )
        devices = await client.get_devices(self.location_id)
        _LOGGER.debug("Fetched %d device(s)", len(devices))
        return {d.device_id: d for d in devices}
    except ConfigEntryAuthFailed:
        raise
    except (WattsApiError, WattsAuthError) as exc:
        raise UpdateFailed(str(exc)) from exc
```

Remove `from typing import Any` if unused. Check: `_ensure_token` uses `dict[str, Any]` on line 53. Keep it.

- [ ] **Step 2: Run all tests**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests still pass (tests don't instantiate the coordinator).

- [ ] **Step 3: Commit**

```bash
git add custom_components/watts_home/coordinator.py
git commit -m "feat: coordinator stores devices as dict[str, WattsDevice] for O(1) lookup"
```

---

## Task 4: Update `tests/test_climate.py` and `climate.py` helpers

Switch the test fixtures to `WattsDevice` (making tests fail), then update the helper functions (making them pass).

**Files:**
- Modify: `tests/test_climate.py`
- Modify: `custom_components/watts_home/climate.py`

- [ ] **Step 1: Update `tests/test_climate.py` to use `WattsDevice`**

Replace the entire file:

```python
"""Unit tests for climate.py mapping helpers using real fixture data."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from homeassistant.components.climate import ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.const import UnitOfTemperature

from custom_components.watts_home.models import WattsDevice

_ROOT = Path(__file__).parent.parent / "custom_components" / "watts_home"
_FIXTURE = Path(__file__).parent / "fixtures" / "devices.json"


def _load(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_const = _load("custom_components.watts_home.const", _ROOT / "const.py")
_climate = _load("custom_components.watts_home.climate", _ROOT / "climate.py")

device_hvac_modes = _climate.device_hvac_modes  # type: ignore[attr-defined]
device_hvac_mode = _climate.device_hvac_mode  # type: ignore[attr-defined]
device_hvac_action = _climate.device_hvac_action  # type: ignore[attr-defined]
device_current_temperature = _climate.device_current_temperature  # type: ignore[attr-defined]
device_current_humidity = _climate.device_current_humidity  # type: ignore[attr-defined]
device_target_temperature = _climate.device_target_temperature  # type: ignore[attr-defined]
device_target_temp_high = _climate.device_target_temp_high  # type: ignore[attr-defined]
device_target_temp_low = _climate.device_target_temp_low  # type: ignore[attr-defined]
device_temperature_unit = _climate.device_temperature_unit  # type: ignore[attr-defined]
device_supported_features = _climate.device_supported_features  # type: ignore[attr-defined]
device_schedule_active = _climate.device_schedule_active  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def devices() -> list[WattsDevice]:
    raw = json.loads(_FIXTURE.read_text())["body"]
    return [WattsDevice.model_validate(d) for d in raw]


def _by_model(devices: list[WattsDevice], model: str) -> WattsDevice:
    for d in devices:
        if d.model_number == model:
            return d
    raise KeyError(model)


# ---------------------------------------------------------------------------
# Model 561 — heat-only, no fan, Cool = null
# ---------------------------------------------------------------------------


class TestModel561:
    def test_hvac_modes(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "561")
        modes = device_hvac_modes(d)
        assert HVACMode.HEAT in modes
        assert HVACMode.OFF in modes
        assert HVACMode.COOL not in modes
        assert HVACMode.HEAT_COOL not in modes

    def test_hvac_mode(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "561")
        assert device_hvac_mode(d) == HVACMode.HEAT

    def test_hvac_action_heating(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "561")
        assert device_hvac_action(d) == HVACAction.HEATING

    def test_current_temperature(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "561")
        temp = device_current_temperature(d)
        assert temp is not None
        assert 40.0 <= temp <= 100.0

    def test_no_humidity(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "561")
        assert device_current_humidity(d) is None

    def test_target_temperature(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "561")
        temp = device_target_temperature(d)
        assert temp is not None

    def test_temperature_unit_fahrenheit(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "561")
        assert device_temperature_unit(d) == UnitOfTemperature.FAHRENHEIT

    def test_supported_features_no_fan_no_range(
        self, devices: list[WattsDevice]
    ) -> None:
        d = _by_model(devices, "561")
        feats = device_supported_features(d)
        assert feats & ClimateEntityFeature.TARGET_TEMPERATURE
        assert feats & ClimateEntityFeature.TURN_ON
        assert feats & ClimateEntityFeature.TURN_OFF
        assert not (feats & ClimateEntityFeature.FAN_MODE)
        assert not (feats & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE)

    def test_schedule_inactive(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "561")
        assert device_schedule_active(d) is False


# ---------------------------------------------------------------------------
# Model 562 — heat/cool/auto, fan, Cool = 95 (sentinel)
# ---------------------------------------------------------------------------


class TestModel562:
    def test_hvac_modes_includes_auto(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "562")
        modes = device_hvac_modes(d)
        assert HVACMode.HEAT in modes
        assert HVACMode.COOL in modes
        assert HVACMode.HEAT_COOL in modes
        assert HVACMode.OFF in modes

    def test_supported_features_has_fan_and_range(
        self, devices: list[WattsDevice]
    ) -> None:
        d = _by_model(devices, "562")
        feats = device_supported_features(d)
        assert feats & ClimateEntityFeature.FAN_MODE
        assert feats & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

    def test_target_temp_high_cool_sentinel(
        self, devices: list[WattsDevice]
    ) -> None:
        d = _by_model(devices, "562")
        # API returns 95 as "not configured" — we expose it as-is
        high = device_target_temp_high(d)
        assert high == 95.0

    def test_target_temp_low_heat(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "562")
        low = device_target_temp_low(d)
        assert low is not None

    def test_hvac_action_off_or_idle(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "562")
        action = device_hvac_action(d)
        assert action in (
            HVACAction.OFF,
            HVACAction.IDLE,
            HVACAction.HEATING,
            HVACAction.COOLING,
        )


# ---------------------------------------------------------------------------
# Model names
# ---------------------------------------------------------------------------


class TestModelNames:
    def test_561_model_name(self, devices: list[WattsDevice]) -> None:
        from custom_components.watts_home.const import MODEL_NAMES  # type: ignore[import]

        assert MODEL_NAMES["561"] == "Tekmar WiFi Thermostat 561"

    def test_562_model_name(self, devices: list[WattsDevice]) -> None:
        from custom_components.watts_home.const import MODEL_NAMES  # type: ignore[import]

        assert MODEL_NAMES["562"] == "Tekmar WiFi Thermostat 562"

    def test_unknown_model_fallback(self, devices: list[WattsDevice]) -> None:
        from custom_components.watts_home.const import MODEL_NAMES  # type: ignore[import]

        model_num = "999"
        name = MODEL_NAMES.get(model_num, f"Tekmar WiFi Thermostat {model_num}")
        assert name == "Tekmar WiFi Thermostat 999"


# ---------------------------------------------------------------------------
# Model 563
# ---------------------------------------------------------------------------


class TestModel563:
    def test_hvac_modes_includes_auto(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "563")
        modes = device_hvac_modes(d)
        assert HVACMode.HEAT_COOL in modes

    def test_supported_features_has_fan(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "563")
        feats = device_supported_features(d)
        assert feats & ClimateEntityFeature.FAN_MODE


# ---------------------------------------------------------------------------
# Null-data robustness
# ---------------------------------------------------------------------------

_NULL_DEVICE: WattsDevice = WattsDevice.model_validate({
    "deviceId": "null-test",
    "name": "Null Device",
    "modelNumber": "561",
    "isConnected": False,
    "data": {
        "Mode": None,
        "State": None,
        "Sensors": None,
        "Target": None,
        "TempUnits": None,
        "SchedEnable": None,
    },
})

_NULL_DATA_FIELD_DEVICE: WattsDevice = WattsDevice.model_validate({
    "deviceId": "null-data-field-test",
    "name": "Null Data Field Device",
    "modelNumber": "561",
    "isConnected": False,
    "data": None,
})


class TestNullDataField:
    """Guards against device.data itself being None."""

    def test_hvac_modes_returns_off(self) -> None:
        assert device_hvac_modes(_NULL_DATA_FIELD_DEVICE) == [HVACMode.OFF]

    def test_hvac_mode_returns_off(self) -> None:
        assert device_hvac_mode(_NULL_DATA_FIELD_DEVICE) == HVACMode.OFF

    def test_hvac_action_returns_none(self) -> None:
        assert device_hvac_action(_NULL_DATA_FIELD_DEVICE) is None

    def test_current_temperature_returns_none(self) -> None:
        assert device_current_temperature(_NULL_DATA_FIELD_DEVICE) is None

    def test_current_humidity_returns_none(self) -> None:
        assert device_current_humidity(_NULL_DATA_FIELD_DEVICE) is None

    def test_target_temperature_returns_none(self) -> None:
        assert device_target_temperature(_NULL_DATA_FIELD_DEVICE) is None

    def test_target_temp_high_returns_none(self) -> None:
        assert device_target_temp_high(_NULL_DATA_FIELD_DEVICE) is None

    def test_target_temp_low_returns_none(self) -> None:
        assert device_target_temp_low(_NULL_DATA_FIELD_DEVICE) is None

    def test_temperature_unit_returns_celsius(self) -> None:
        assert (
            device_temperature_unit(_NULL_DATA_FIELD_DEVICE)
            == UnitOfTemperature.CELSIUS
        )

    def test_supported_features_does_not_raise(self) -> None:
        feats = device_supported_features(_NULL_DATA_FIELD_DEVICE)
        assert feats & ClimateEntityFeature.TURN_ON
        assert feats & ClimateEntityFeature.TURN_OFF

    def test_schedule_active_returns_false(self) -> None:
        assert device_schedule_active(_NULL_DATA_FIELD_DEVICE) is False


class TestNullData:
    def test_hvac_modes_returns_off(self) -> None:
        assert device_hvac_modes(_NULL_DEVICE) == [HVACMode.OFF]

    def test_hvac_mode_returns_off(self) -> None:
        assert device_hvac_mode(_NULL_DEVICE) == HVACMode.OFF

    def test_hvac_action_returns_none(self) -> None:
        assert device_hvac_action(_NULL_DEVICE) is None

    def test_current_temperature_returns_none(self) -> None:
        assert device_current_temperature(_NULL_DEVICE) is None

    def test_current_humidity_returns_none(self) -> None:
        assert device_current_humidity(_NULL_DEVICE) is None

    def test_target_temperature_returns_none(self) -> None:
        assert device_target_temperature(_NULL_DEVICE) is None

    def test_target_temp_high_returns_none(self) -> None:
        assert device_target_temp_high(_NULL_DEVICE) is None

    def test_target_temp_low_returns_none(self) -> None:
        assert device_target_temp_low(_NULL_DEVICE) is None

    def test_temperature_unit_returns_celsius_default(self) -> None:
        assert device_temperature_unit(_NULL_DEVICE) == UnitOfTemperature.CELSIUS

    def test_supported_features_does_not_raise(self) -> None:
        feats = device_supported_features(_NULL_DEVICE)
        assert feats & ClimateEntityFeature.TURN_ON
        assert feats & ClimateEntityFeature.TURN_OFF

    def test_schedule_active_returns_false(self) -> None:
        assert device_schedule_active(_NULL_DEVICE) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_climate.py -v
```

Expected: failures like `AttributeError: 'WattsDevice' object has no attribute 'get'` because the helpers still call `device.get("data")`.

- [ ] **Step 3: Replace all helper functions in `climate.py`**

Replace the helper functions section of `climate.py` (lines 52–164) with:

```python
def device_hvac_modes(device: WattsDevice) -> list[HVACMode]:
    if device.data is None or device.data.mode is None:
        return [HVACMode.OFF]
    return [
        _HA_MODE_MAP[ha]
        for w in device.data.mode.enum
        if (ha := WATTS_TO_HA_MODE.get(w)) is not None and ha in _HA_MODE_MAP
    ]


def device_hvac_mode(device: WattsDevice) -> HVACMode:
    if device.data is None or device.data.mode is None:
        return HVACMode.OFF
    ha = WATTS_TO_HA_MODE.get(device.data.mode.val, "off")
    return _HA_MODE_MAP.get(ha, HVACMode.OFF)


def device_hvac_action(device: WattsDevice) -> HVACAction | None:
    if device.data is None or device.data.state is None:
        return None
    ha = WATTS_TO_HA_ACTION.get(device.data.state.op)
    if ha is None:
        return None
    return _HA_ACTION_MAP.get(ha)


def device_current_temperature(device: WattsDevice) -> float | None:
    if device.data is None or device.data.sensors is None:
        return None
    room = device.data.sensors.room
    if room is None:
        return None
    return room.val if room.status == "Okay" else None


def device_current_humidity(device: WattsDevice) -> float | None:
    if device.data is None or device.data.sensors is None:
        return None
    rh = device.data.sensors.rh
    return rh.val if rh and rh.status == "Okay" else None


def device_target_temperature(device: WattsDevice) -> float | None:
    """Single setpoint — used in heat or cool mode."""
    mode = device_hvac_mode(device)
    if device.data is None or device.data.target is None:
        return None
    if mode == HVACMode.COOL:
        return device.data.target.cool
    return device.data.target.heat


def device_target_temp_high(device: WattsDevice) -> float | None:
    """Cool setpoint for heat_cool mode."""
    if device.data is None or device.data.target is None:
        return None
    return device.data.target.cool


def device_target_temp_low(device: WattsDevice) -> float | None:
    """Heat setpoint for heat_cool mode."""
    if device.data is None or device.data.target is None:
        return None
    return device.data.target.heat


def device_temperature_unit(device: WattsDevice) -> str:
    if device.data is None or device.data.temp_units is None:
        return UnitOfTemperature.CELSIUS
    return (
        UnitOfTemperature.FAHRENHEIT
        if device.data.temp_units.val == "F"
        else UnitOfTemperature.CELSIUS
    )


def device_supported_features(device: WattsDevice) -> ClimateEntityFeature:
    features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    if HVACMode.HEAT_COOL in device_hvac_modes(device):
        features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
    if device.data and device.data.fan and device.data.fan.enum:
        features |= ClimateEntityFeature.FAN_MODE
    return features


def device_schedule_active(device: WattsDevice) -> bool:
    if device.data is None or device.data.sched_enable is None:
        return False
    return device.data.sched_enable.val.lower() in ("on", "enabled")
```

Update the import block at the top of `climate.py` — replace `from typing import Any` with the `WattsDevice` import, and remove `Any` from the `from typing import Any` line (keep the line if `Any` is still used in `async_set_temperature`, otherwise remove it):

```python
from typing import Any

from .models import WattsDevice
```

`Any` is still used in `async_set_temperature(**kwargs: Any)`, so keep it.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_climate.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_climate.py custom_components/watts_home/climate.py
git commit -m "refactor: climate helpers accept WattsDevice instead of dict"
```

---

## Task 5: Update `climate.py` entity class and `async_setup_entry`

**Files:**
- Modify: `custom_components/watts_home/climate.py`

- [ ] **Step 1: Update the `async_setup_entry` function**

Replace `async_setup_entry` (lines 171–179) with the discovery-listener version.

Add `callback` to the HA core import:

```python
from homeassistant.core import HomeAssistant, callback
```

Replace `async_setup_entry`:

```python
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WattsDataUpdateCoordinator = entry.runtime_data
    known_device_ids: set[str] = set()

    @callback
    def _async_add_new() -> None:
        new = [
            WattsClimateEntity(coordinator, device_id)
            for device_id in coordinator.data
            if device_id not in known_device_ids
        ]
        if new:
            known_device_ids.update(e._device_id for e in new)
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))
    _async_add_new()
```

- [ ] **Step 2: Update `WattsClimateEntity.__init__`, `_device()`, `available`, and inline properties**

Replace the entire `WattsClimateEntity` class body (lines 187–330) with:

```python
class WattsClimateEntity(CoordinatorEntity[WattsDataUpdateCoordinator], ClimateEntity):
    """Thermostat entity for a single Watts/Tekmar device."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        coordinator: WattsDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = device_id
        device = coordinator.data[device_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device.name,
            model=MODEL_NAMES.get(
                device.model_number, f"Tekmar WiFi Thermostat {device.model_number}"
            ),
            manufacturer="Watts Home",
        )

    def _device(self) -> WattsDevice:
        return self.coordinator.data[self._device_id]  # KeyError → available=False

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        try:
            return self._device().is_connected
        except KeyError:
            return False

    @property
    def hvac_modes(self) -> list[HVACMode]:
        return device_hvac_modes(self._device())

    @property
    def hvac_mode(self) -> HVACMode:
        return device_hvac_mode(self._device())

    @property
    def hvac_action(self) -> HVACAction | None:
        return device_hvac_action(self._device())

    @property
    def current_temperature(self) -> float | None:
        return device_current_temperature(self._device())

    @property
    def current_humidity(self) -> float | None:
        return device_current_humidity(self._device())

    @property
    def target_temperature(self) -> float | None:
        if HVACMode.HEAT_COOL in self.hvac_modes:
            return None
        return device_target_temperature(self._device())

    @property
    def target_temperature_high(self) -> float | None:
        if HVACMode.HEAT_COOL not in self.hvac_modes:
            return None
        return device_target_temp_high(self._device())

    @property
    def target_temperature_low(self) -> float | None:
        if HVACMode.HEAT_COOL not in self.hvac_modes:
            return None
        return device_target_temp_low(self._device())

    @property
    def min_temp(self) -> float:
        d = self._device()
        return d.data.target.min if d.data and d.data.target else 40.0

    @property
    def max_temp(self) -> float:
        d = self._device()
        return d.data.target.max if d.data and d.data.target else 95.0

    @property
    def target_temperature_step(self) -> float:
        d = self._device()
        return d.data.target.steps if d.data and d.data.target else 1.0

    @property
    def temperature_unit(self) -> str:
        return device_temperature_unit(self._device())

    @property
    def fan_mode(self) -> str | None:
        d = self._device()
        return d.data.fan.val if d.data and d.data.fan else None

    @property
    def fan_modes(self) -> list[str] | None:
        d = self._device()
        return d.data.fan.enum if d.data and d.data.fan else None

    @property
    def supported_features(self) -> ClimateEntityFeature:
        return device_supported_features(self._device())

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        watts_mode = HA_TO_WATTS_MODE[hvac_mode]
        client = await self.coordinator.async_get_client()
        await client.set_mode(self._device_id, watts_mode)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        modes = [m for m in self.hvac_modes if m != HVACMode.OFF]
        if modes:
            await self.async_set_hvac_mode(modes[0])

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        device = self._device()
        sched = device_schedule_active(device)
        client = await self.coordinator.async_get_client()

        if ATTR_TARGET_TEMP_HIGH in kwargs or ATTR_TARGET_TEMP_LOW in kwargs:
            heat = kwargs.get(ATTR_TARGET_TEMP_LOW)
            cool = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        else:
            temp = kwargs.get(ATTR_TEMPERATURE)
            mode = device_hvac_mode(device)
            heat = temp if mode == HVACMode.HEAT else None
            cool = temp if mode == HVACMode.COOL else None

        await client.set_temperature(self._device_id, sched, heat, cool)
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        client = await self.coordinator.async_get_client()
        await client.set_fan_mode(self._device_id, fan_mode)
        await self.coordinator.async_request_refresh()
```

- [ ] **Step 3: Run all tests**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add custom_components/watts_home/climate.py
git commit -m "feat: climate entity uses typed WattsDevice lookup and dynamic discovery listener"
```

---

## Task 6: Update `tests/test_sensor.py` and `sensor.py`

Switch sensor tests to `WattsDevice` (making them fail), then update `sensor.py`.

**Files:**
- Modify: `tests/test_sensor.py`
- Modify: `custom_components/watts_home/sensor.py`

- [ ] **Step 1: Update `tests/test_sensor.py` to use `WattsDevice`**

Replace the entire file:

```python
"""Unit tests for sensor.py using real fixture data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.watts_home.models import WattsDevice

_FIXTURE = Path(__file__).parent / "fixtures" / "devices.json"


@pytest.fixture(scope="module")
def devices() -> list[WattsDevice]:
    raw = json.loads(_FIXTURE.read_text())["body"]
    return [WattsDevice.model_validate(d) for d in raw]


def _by_model(devices: list[WattsDevice], model: str) -> WattsDevice:
    for d in devices:
        if d.model_number == model:
            return d
    raise KeyError(model)


def _by_name(devices: list[WattsDevice], name: str) -> WattsDevice:
    for d in devices:
        if d.name == name:
            return d
    raise KeyError(name)


class TestOutdoorSensorEligibility:
    def test_562_has_outdoor_okay(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "562")
        assert d.data is not None
        assert d.data.sensors is not None
        assert d.data.sensors.outdoor is not None
        assert d.data.sensors.outdoor.status == "Okay"

    def test_561_outdoor_absent(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "561")
        assert d.data is not None
        assert d.data.sensors is not None
        outdoor = d.data.sensors.outdoor
        assert outdoor is None or outdoor.status != "Okay"

    def test_563_has_outdoor_okay(self, devices: list[WattsDevice]) -> None:
        d = _by_name(devices, "Living")
        assert d.data is not None
        assert d.data.sensors is not None
        assert d.data.sensors.outdoor is not None
        assert d.data.sensors.outdoor.status == "Okay"


class TestHumiditySensorEligibility:
    def test_563_living_has_rh_okay(self, devices: list[WattsDevice]) -> None:
        d = _by_name(devices, "Living")
        assert d.data is not None
        assert d.data.sensors is not None
        rh = d.data.sensors.rh
        assert rh is not None
        assert rh.status == "Okay"
        assert isinstance(rh.val, float)

    def test_562_no_rh_okay(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "562")
        assert d.data is not None
        assert d.data.sensors is not None
        rh = d.data.sensors.rh
        assert rh is None or rh.status != "Okay"

    def test_561_no_rh(self, devices: list[WattsDevice]) -> None:
        d = _by_model(devices, "561")
        assert d.data is not None
        assert d.data.sensors is not None
        rh = d.data.sensors.rh
        assert rh is None or rh.status != "Okay"


class TestSensorCounts:
    """Verify the expected number of sensor entities created from the fixture."""

    def test_outdoor_sensor_count(self, devices: list[WattsDevice]) -> None:
        outdoor_count = sum(
            1
            for d in devices
            if d.data
            and d.data.sensors
            and d.data.sensors.outdoor
            and d.data.sensors.outdoor.status == "Okay"
        )
        # From fixture: 4 devices (3x562, 1x563) have Outdoor Status=Okay
        assert outdoor_count == 4

    def test_humidity_sensor_count(self, devices: list[WattsDevice]) -> None:
        rh_count = sum(
            1
            for d in devices
            if d.data
            and d.data.sensors
            and d.data.sensors.rh
            and d.data.sensors.rh.status == "Okay"
        )
        # From fixture: only "Living" (563) has RH Status=Okay
        assert rh_count == 1


_NULL_DATA_FIELD_DEVICE: WattsDevice = WattsDevice.model_validate({
    "deviceId": "null-data-field",
    "name": "Null Data Field Device",
    "modelNumber": "561",
    "isConnected": False,
    "data": None,
})


class TestNullDataSensor:
    """Guards against device.data being None in sensor setup and entity methods."""

    def test_outdoor_eligibility_skips_null_data_device(
        self, devices: list[WattsDevice]
    ) -> None:
        all_devices = [*devices, _NULL_DATA_FIELD_DEVICE]
        outdoor_count = sum(
            1
            for d in all_devices
            if d.data
            and d.data.sensors
            and d.data.sensors.outdoor
            and d.data.sensors.outdoor.status == "Okay"
        )
        assert outdoor_count == 4

    def test_rh_eligibility_skips_null_data_device(
        self, devices: list[WattsDevice]
    ) -> None:
        all_devices = [*devices, _NULL_DATA_FIELD_DEVICE]
        rh_count = sum(
            1
            for d in all_devices
            if d.data
            and d.data.sensors
            and d.data.sensors.rh
            and d.data.sensors.rh.status == "Okay"
        )
        assert rh_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_sensor.py -v
```

Expected: `KeyError` or `AttributeError` in `TestSensorCounts` and `TestNullDataSensor` because the old inline tests that used `d["data"]["Sensors"]` are now using `d.data.sensors` which works, but `TestOutdoorSensorEligibility` previously accessed raw dict keys — those now access `WattsDevice` attributes correctly. The tests that access the old module-level `_sensor_mod` import are gone. Verify at least some tests fail.

- [ ] **Step 3: Update `sensor.py`**

Replace the entire file:

```python
"""Sensor platform for the Watts Home (Tekmar) integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL_NAMES
from .coordinator import WattsDataUpdateCoordinator
from .models import WattsDevice


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WattsDataUpdateCoordinator = entry.runtime_data
    known_entity_ids: set[str] = set()

    @callback
    def _async_add_new() -> None:
        new: list[SensorEntity] = []
        for device_id, device in coordinator.data.items():
            s = device.data.sensors if device.data else None
            if s and s.outdoor and s.outdoor.status == "Okay":
                uid = f"{device_id}_outdoor_temp"
                if uid not in known_entity_ids:
                    known_entity_ids.add(uid)
                    new.append(WattsOutdoorTempSensor(coordinator, device_id))
            if s and s.rh and s.rh.status == "Okay":
                uid = f"{device_id}_humidity"
                if uid not in known_entity_ids:
                    known_entity_ids.add(uid)
                    new.append(WattsHumiditySensor(coordinator, device_id))
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))
    _async_add_new()


def _device_info(device: WattsDevice) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, device.device_id)},
        name=device.name,
        model=MODEL_NAMES.get(
            device.model_number, f"Tekmar WiFi Thermostat {device.model_number}"
        ),
        manufacturer="Watts Home",
    )


class WattsOutdoorTempSensor(
    CoordinatorEntity[WattsDataUpdateCoordinator], SensorEntity
):
    """Outdoor temperature sensor for a Watts/Tekmar device."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_translation_key = "outdoor_temperature"

    def __init__(
        self,
        coordinator: WattsDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_outdoor_temp"
        device = coordinator.data[device_id]
        self._attr_device_info = _device_info(device)
        unit = device.data.temp_units.val if device.data and device.data.temp_units else None
        self._attr_native_unit_of_measurement = (
            UnitOfTemperature.FAHRENHEIT if unit == "F" else UnitOfTemperature.CELSIUS
        )

    def _device(self) -> WattsDevice:
        return self.coordinator.data[self._device_id]  # KeyError → available=False

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        try:
            d = self._device()
            s = d.data.sensors if d.data else None
            return (
                d.is_connected
                and s is not None
                and s.outdoor is not None
                and s.outdoor.status == "Okay"
            )
        except KeyError:
            return False

    @property
    def native_value(self) -> float | None:
        d = self._device()
        s = d.data.sensors if d.data else None
        if s and s.outdoor and s.outdoor.status == "Okay":
            return s.outdoor.val
        return None


class WattsHumiditySensor(CoordinatorEntity[WattsDataUpdateCoordinator], SensorEntity):
    """Relative humidity sensor for a Watts/Tekmar device."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_has_entity_name = True
    _attr_translation_key = "humidity"

    def __init__(
        self,
        coordinator: WattsDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_humidity"
        self._attr_device_info = _device_info(coordinator.data[device_id])

    def _device(self) -> WattsDevice:
        return self.coordinator.data[self._device_id]  # KeyError → available=False

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        try:
            d = self._device()
            s = d.data.sensors if d.data else None
            return (
                d.is_connected
                and s is not None
                and s.rh is not None
                and s.rh.status == "Okay"
            )
        except KeyError:
            return False

    @property
    def native_value(self) -> float | None:
        d = self._device()
        s = d.data.sensors if d.data else None
        if s and s.rh and s.rh.status == "Okay":
            return s.rh.val
        return None
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests PASS, including `test_models.py`, `test_climate.py`, and `test_sensor.py`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_sensor.py custom_components/watts_home/sensor.py
git commit -m "feat: sensor entities use typed WattsDevice lookup and dynamic discovery listener"
```
