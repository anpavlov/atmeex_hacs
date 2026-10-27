"""Sign-in form and reauth repair while the Atmeex cloud is down."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir

from custom_components.atmeex_cloud.const import DOMAIN

ENTRY_ID = "01TESTENTRY"
DEVICE = {
    "id": 1, "mac": "AA:BB:CC:DD:EE:FF", "type": 1, "name": "Bedroom", "room_id": 2, "owner_id": 3,
    "created_at": "", "socket_id": "", "fw_ver": "1.9/3.5/2.11", "model": "A7", "online": False,
    "settings": {
        "id": 0, "device_id": 1, "u_pwr_on": True, "u_fan_speed": 0, "u_damp_pos": 0, "u_hum_stg": 2,
        "u_temp_room": 100, "u_auto": True, "u_night": False, "u_cool_mode": False,
        "u_night_start": "20:00", "u_night_stop": "10:00", "u_time_zone": 3,
    },
}


class FakeCloud:
    """Answers like the Atmeex API in one of: up, down, rejecting the saved tokens."""

    def __init__(self, mode: str = "down") -> None:
        self.mode = mode

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.mode == "down":
            raise httpx.ConnectError("All connection attempts failed", request=request)

        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path == "/auth/signup":
            return httpx.Response(200, json={})
        if path == "/auth/signin":
            if self.mode == "rejecting" and body.get("grant_type") == "refresh_token":
                return httpx.Response(401, json={})
            return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh"})
        if path == "/devices":
            if self.mode == "rejecting":
                return httpx.Response(401, json={})
            return httpx.Response(200, json=[DEVICE])
        return httpx.Response(404)

    def client(self, *_args, **_kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def reauth_issue(hass):
    return ir.async_get(hass).async_get_issue("homeassistant", f"config_entry_reauth_{DOMAIN}_{ENTRY_ID}")


def reauth_flows(hass):
    return hass.config_entries.flow.async_progress_by_handler(DOMAIN, match_context={"source": SOURCE_REAUTH})


@pytest.fixture
def cloud():
    fake = FakeCloud()
    with (
        patch("custom_components.atmeex_cloud.create_async_httpx_client", fake.client),
        patch("custom_components.atmeex_cloud.config_flow.create_async_httpx_client", fake.client),
    ):
        yield fake


@pytest.fixture
async def local_entry(hass, hass_storage, cloud):
    """Local server mode with the stored device list, breezers not connected yet."""
    hass_storage[f"{DOMAIN}.{ENTRY_ID}"] = {"version": 1, "key": f"{DOMAIN}.{ENTRY_ID}", "data": [DEVICE]}
    entry = MockConfigEntry(
        domain=DOMAIN, entry_id=ENTRY_ID, unique_id="+70000000000", title="+70000000000",
        data={"phone": "+70000000000", "access_token": "expired", "refresh_token": "unknown"},
        options={"local_server": True},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.atmeex_cloud.local.AtmeexLocalServer.async_start", AsyncMock()),
        patch("custom_components.atmeex_cloud.local.AtmeexLocalServer.async_stop", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry


async def poll(hass, entry):
    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()


async def test_phone_step_cloud_down(hass, cloud):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"auth_method": "auth_method_phone"})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"phone": "+70000000000"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "phone"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_phone_code_step_cloud_down(hass, cloud):
    cloud.mode = "up"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"auth_method": "auth_method_phone"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"phone": "+70000000000"})
    assert result["step_id"] == "phone_code"

    cloud.mode = "down"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"phone_code": "123456"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "phone_code"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_email_step_cloud_down(hass, cloud):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"auth_method": "auth_method_email"})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "user@example.com", "password": "secret"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "email"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_cloud_down_opens_no_repair(hass, local_entry, cloud):
    await poll(hass, local_entry)

    assert reauth_issue(hass) is None
    assert not reauth_flows(hass)


async def test_repair_only_while_cloud_answers(hass, local_entry, cloud):
    cloud.mode = "rejecting"
    await poll(hass, local_entry)
    assert reauth_issue(hass) is not None
    assert len(reauth_flows(hass)) == 1

    cloud.mode = "down"
    await poll(hass, local_entry)
    assert reauth_issue(hass) is None
    assert not reauth_flows(hass)

    cloud.mode = "rejecting"
    await poll(hass, local_entry)
    assert reauth_issue(hass) is not None
    assert len(reauth_flows(hass)) == 1


async def test_repeated_refusal_keeps_one_repair(hass, local_entry, cloud):
    cloud.mode = "rejecting"
    await poll(hass, local_entry)
    flow_id = reauth_flows(hass)[0]["flow_id"]

    await poll(hass, local_entry)

    assert [flow["flow_id"] for flow in reauth_flows(hass)] == [flow_id]


async def test_reauth_completes_when_cloud_is_back(hass, local_entry, cloud):
    cloud.mode = "rejecting"
    await poll(hass, local_entry)
    flow_id = reauth_flows(hass)[0]["flow_id"]

    cloud.mode = "up"
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    assert result["step_id"] == "phone"
    result = await hass.config_entries.flow.async_configure(flow_id, {"phone": "+70000000000"})
    with (
        patch("custom_components.atmeex_cloud.local.AtmeexLocalServer.async_start", AsyncMock()),
        patch("custom_components.atmeex_cloud.local.AtmeexLocalServer.async_stop", AsyncMock()),
    ):
        result = await hass.config_entries.flow.async_configure(flow_id, {"phone_code": "123456"})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert local_entry.data["access_token"] == "new-access"
    assert reauth_issue(hass) is None
