"""Device list as the Atmeex cloud sends it since its October 2026 restart: fields atmeexpy requires are gone."""

import json
from unittest.mock import patch

import httpx
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr

from custom_components.atmeex_cloud.const import DOMAIN

# No socket_id and fw_ver, settings without id, device_id and u_cool_mode, booleans in condition
DEVICE = {
    "condition": {
        "co2_ppm": 686, "created_at": "2026-10-27 14:28:43", "damp_pos": 0, "device_id": 1, "fan_speed": 0,
        "firmware_version": "1.9/3.6/2.11", "hum_room": 38, "hum_stg": 3, "no_water": True, "pwr_on": True,
        "temp_in": 132, "temp_room": 154, "time": "2026-10-27 14:28:43",
    },
    "created_at": "2026-10-27 14:16:18", "force_init": False, "id": 1, "mac": "AA:BB:CC:DD:EE:FF", "model": "A7",
    "name": "Bedroom", "online": True, "owner_id": 3, "room_id": 2, "scenarios": [],
    "settings": {
        "u_auto": True, "u_damp_pos": 0, "u_fan_speed": 0, "u_hum_stg": 3, "u_night": False,
        "u_night_start": "20:00", "u_night_stop": "10:00", "u_pwr_on": True, "u_temp_room": 100,
    },
    "type": 1, "updated_at": "2026-10-27 14:16:38",
}
GOOD_CODE = "1234"


class FakeCloud:
    def __init__(self) -> None:
        self.sms_sent = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path == "/auth/signup":
            self.sms_sent += 1
            return httpx.Response(200, json={"success": True})
        if path == "/auth/signin":
            if body.get("phone_code") != GOOD_CODE:
                return httpx.Response(401, json={"message": "Неверный код"})
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"})
        if path == "/devices":
            return httpx.Response(200, json=[json.loads(json.dumps(DEVICE))])
        return httpx.Response(404)

    def client(self, *_args, **_kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def cloud():
    fake = FakeCloud()
    with (
        patch("custom_components.atmeex_cloud.create_async_httpx_client", fake.client),
        patch("custom_components.atmeex_cloud.config_flow.create_async_httpx_client", fake.client),
    ):
        yield fake


async def start_phone_sign_in(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"auth_method": "auth_method_phone"})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"phone": "+70000000000"})


async def test_sign_in_finds_devices(hass, cloud):
    result = await start_phone_sign_in(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"phone_code": GOOD_CODE})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_wrong_code_asks_for_new_sms(hass, cloud):
    result = await start_phone_sign_in(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"phone_code": "0000"})
    assert result["step_id"] == "phone"
    assert result["errors"] == {"base": "invalid_code"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"phone": "+70000000000"})
    assert result["step_id"] == "phone_code"
    assert cloud.sms_sent == 2


async def test_entities_from_new_format(hass, cloud):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="+70000000000", title="+70000000000",
        data={"phone": "+70000000000", "access_token": "access", "refresh_token": "refresh"},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    climate = hass.states.get("climate.bedroom")
    assert climate is not None
    assert climate.attributes["current_temperature"] == 15.4
    assert hass.states.get("binary_sensor.bedroom_no_water").state == "on"
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "1"), entry.entry_id)
    assert device.sw_version == "1.9/3.6/2.11"
