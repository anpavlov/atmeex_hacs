"""Local server that stands in for the Atmeex cloud.

Breezers keep a plain TCP connection to the cloud (ws.iot.atmeex.com:3001) and exchange JSON messages with it:
the breezer sends hello, setp (its settings) and state (readings, every 5 s), the cloud answers hello and sends cmd.
A router rule that redirects these connections to Home Assistant lets the breezers work without the cloud.
Home Assistant can also keep a cloud connection for each breezer and relay messages, so the Atmeex app keeps working.
"""

import asyncio
import codecs
import json
import logging
from collections.abc import Callable

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

LOCAL_PORT = 3001
CLOUD_HOST = "ws.iot.atmeex.com"
CLOUD_PORT = 3001
CLOUD_TIMEOUT = 10
CLOUD_RETRY_INTERVAL = 60
# Drop the cloud connection if the cloud stops reading
MAX_CLOUD_BACKLOG = 65536
# A hello sent to the cloud that comes back to this server in this time means a loop
LOOP_WINDOW = 10

# Breezers report every 5 s: after this silence ask for the state, after MAX_SILENT_PERIODS drop the connection
SILENCE_TIMEOUT = 20
MAX_SILENT_PERIODS = 3

MAX_BUFFER = 16384

# Settings a breezer reports in setp; anything else is dropped, so settings always fit DeviceSettingsModel
SETTING_TYPES = {
    "u_pwr_on": bool,
    "u_fan_speed": int,
    "u_damp_pos": int,
    "u_hum_stg": int,
    "u_temp_room": int,
    "u_auto": bool,
    "u_night": bool,
    "u_cool_mode": bool,
    "u_night_start": str,
    "u_night_stop": str,
}

_DECODER = json.JSONDecoder()


def split_messages(text: str) -> tuple[list, str]:
    """Split the stream into JSON messages, return them and the incomplete rest.

    Breezers send messages back to back without separators.
    """
    messages = []
    pos = 0
    while True:
        start = text.find("{", pos)
        if start == -1:
            return messages, ""

        try:
            message, pos = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            # Wait for the rest of an incomplete message; once the next one starts, this one is broken
            pos = text.find('{"id"', start + 1)
            if pos == -1:
                return messages, text[start:]
            continue

        messages.append(message)


def _time_zone() -> str:
    """Home Assistant time zone the way the cloud sends it to breezers: 03:00 for UTC+3."""
    minutes = int(dt_util.now().utcoffset().total_seconds()) // 60
    sign = "-" if minutes < 0 else ""
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def _encode(message: dict) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode()


def _commands(params: dict) -> dict:
    """Turn settings named like in the cloud API (u_fan_speed) into breezer commands (set_fan_speed)."""
    return {f"set_{key.removeprefix('u_')}": value for key, value in params.items()}


class AtmeexLocalSession:
    """Connection of one breezer."""

    def __init__(self, device_id: str, writer: asyncio.StreamWriter):
        self.device_id = device_id
        self.settings: dict = {}
        self.state: dict | None = None
        self.fw_ver: str | None = None
        self.hello: dict | None = None
        self.cloud: asyncio.StreamWriter | None = None
        self.cloud_task: asyncio.Task | None = None
        self._writer = writer

    @property
    def ready(self) -> bool:
        """Settings and readings have arrived."""
        return bool(self.settings) and self.state is not None

    async def async_write(self, message: dict) -> None:
        if self._writer.is_closing():
            raise ConnectionError(f"Breezer {self.device_id} disconnected")

        self._writer.write(_encode(message) + b"\n")
        await self._writer.drain()

    def relay_to_cloud(self, message: dict) -> None:
        """Pass a breezer message on to the cloud connection, if there is one."""
        if self.cloud is None or self.cloud.is_closing():
            return

        # Breezers send messages without separators
        self.cloud.write(_encode(message))
        if self.cloud.transport.get_write_buffer_size() > MAX_CLOUD_BACKLOG:
            _LOGGER.warning("Atmeex cloud doesn't read messages of breezer %s, disconnecting", self.device_id)
            # close() would wait for the cloud to read the backlog
            self.cloud.transport.abort()

    async def async_send_command(self, command: dict) -> None:
        await self.async_write({"id": self.device_id, "cmd": command})

    async def async_set_params(self, params: dict) -> None:
        """Change settings named like in the cloud API."""
        await self.async_send_command(_commands(params))
        # The breezer confirms with setp; until then show what was asked
        self.settings.update(params)

    def close(self) -> None:
        self._writer.close()


class AtmeexLocalServer:
    """Accepts breezer connections and keeps their latest settings and readings."""

    def __init__(
        self, port: int, is_known: Callable[[str], bool], on_update: Callable[[], None], relay_to_cloud: bool = False
    ):
        self.sessions: dict[str, AtmeexLocalSession] = {}
        self._port = port
        self._is_known = is_known
        self._on_update = on_update
        self._relay_to_cloud = relay_to_cloud
        self._relay_tasks: set[asyncio.Task] = set()
        # Hellos sent to the cloud and when, to notice them coming back to this server
        self._relayed_hellos: dict[bytes, float] = {}
        self._server: asyncio.Server | None = None

    @property
    def port(self) -> int:
        return self._server.sockets[0].getsockname()[1]

    async def async_start(self) -> None:
        # Breezers only use IPv4
        self._server = await asyncio.start_server(self._async_handle_connection, "0.0.0.0", self._port)

    async def async_stop(self) -> None:
        if self._server is None:
            return

        self._server.close()
        self._server.close_clients()
        for task in self._relay_tasks:
            task.cancel()
        await asyncio.gather(*self._relay_tasks, return_exceptions=True)
        await self._server.wait_closed()
        self._server = None

    async def _async_handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        session = None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""
        silent_periods = 0
        try:
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(4096), SILENCE_TIMEOUT)
                except TimeoutError:
                    silent_periods += 1
                    if session is None or silent_periods > MAX_SILENT_PERIODS:
                        break

                    # A breezer may stop reporting on its own but still answers requests
                    await session.async_send_command({"get_state": True})
                    continue

                if not data:
                    break

                silent_periods = 0
                messages, buffer = split_messages(buffer + decoder.decode(data))
                if len(buffer) > MAX_BUFFER:
                    _LOGGER.warning("Closing connection from %s: unexpected data", writer.get_extra_info("peername"))
                    break

                for message in messages:
                    session = await self._async_handle_message(session, message, writer)
                    if session is None:
                        return
        except OSError as err:
            _LOGGER.debug("Breezer connection error: %s", err)
        finally:
            writer.close()
            if session is not None and session.cloud_task is not None:
                session.cloud_task.cancel()
            if session is not None and self.sessions.get(session.device_id) is session:
                del self.sessions[session.device_id]
                _LOGGER.info("Breezer %s disconnected", session.device_id)
                self._on_update()

    async def _async_handle_message(
        self, session: AtmeexLocalSession | None, message, writer: asyncio.StreamWriter
    ) -> AtmeexLocalSession | None:
        """Handle one message, return the session of the connection or None to close it."""
        if not isinstance(message, dict) or not isinstance(message.get("id"), str):
            return session

        device_id = message["id"].upper()
        if session is None:
            sent = self._relayed_hellos.get(_encode(message)) if "hello" in message else None
            if sent is not None and asyncio.get_running_loop().time() - sent < LOOP_WINDOW:
                self._stop_relaying("the router sends Home Assistant's own connections to the cloud back to it")
                return None

            if not self._is_known(device_id):
                _LOGGER.warning("Closing connection from unknown device %s", device_id)
                return None

            session = self._register(device_id, writer)
        elif device_id != session.device_id:
            return session

        if "hello" not in message:
            session.relay_to_cloud(message)

        if isinstance(hello := message.get("hello"), dict):
            await self._async_handle_hello(session, hello)
        elif isinstance(setp := message.get("setp"), dict):
            session.settings.update({k: v for k, v in setp.items() if type(v) is SETTING_TYPES.get(k)})
            self._on_update()
        elif isinstance(state := message.get("state"), dict):
            # The state comes every 5 s with a new time; update entities only when readings change
            changed = session.state is None or {**session.state, "time": None} != {**state, "time": None}
            session.state = state
            if changed:
                self._on_update()

        return session

    def _register(self, device_id: str, writer: asyncio.StreamWriter) -> AtmeexLocalSession:
        _LOGGER.info("Breezer %s connected from %s", device_id, writer.get_extra_info("peername"))
        session = AtmeexLocalSession(device_id, writer)
        if (old := self.sessions.get(device_id)) is not None:
            # The breezer reconnected; the cloud drops the old connection too.
            # Keep what it reported so far, so that its entities don't blink unavailable
            old.close()
            session.settings = dict(old.settings)
            session.state = old.state
            session.fw_ver = old.fw_ver

        self.sessions[device_id] = session
        return session

    async def _async_handle_hello(self, session: AtmeexLocalSession, hello: dict) -> None:
        if isinstance(hello.get("fw_ver"), str):
            session.fw_ver = hello["fw_ver"]
        first_hello = session.hello is None
        session.hello = hello

        await session.async_write({
            "hello": True,
            "id": session.device_id,
            "time": dt_util.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "time_zone": hello.get("time_zone", "-00:00"),
        })

        if hello.get("init_req"):
            # A breezer set up anew asks for its time zone and settings, the cloud sends them in one command.
            # Only settings the breezer itself reported are sent back: the cloud's copy may be outdated
            await session.async_send_command({"set_time_zone": _time_zone(), **_commands(session.settings)})

        await session.async_send_command({"get_setp": True})
        await session.async_send_command({"get_state": True})

        if first_hello and self._relay_to_cloud:
            session.cloud_task = asyncio.create_task(self._async_keep_cloud_connection(session))
            self._relay_tasks.add(session.cloud_task)
            session.cloud_task.add_done_callback(self._relay_tasks.discard)

    async def _async_keep_cloud_connection(self, session: AtmeexLocalSession) -> None:
        """Connect the breezer to the cloud through Home Assistant and keep it connected."""
        init_req = session.hello.get("init_req", False)
        while True:
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(CLOUD_HOST, CLOUD_PORT), CLOUD_TIMEOUT)
            except (OSError, TimeoutError) as err:
                _LOGGER.debug("Can't connect breezer %s to the Atmeex cloud: %s", session.device_id, err)
            else:
                if self._is_own_address(writer):
                    writer.close()
                    self._stop_relaying(f"{CLOUD_HOST} points to Home Assistant itself")
                    return

                # The time of Home Assistant also tells this hello from the breezer's own ones when looking for a loop
                hello = {**session.hello, "init_req": init_req, "time": dt_util.utcnow().strftime("%Y-%m-%d %H:%M:%S")}
                await self._async_relay_from_cloud(session, hello, reader, writer)

            await asyncio.sleep(CLOUD_RETRY_INTERVAL)
            # Later the cloud only gets a hello with init_req off: in reply to init_req it sends the settings it
            # stored, which are outdated after a break
            init_req = False

    def _stop_relaying(self, reason: str) -> None:
        """The cloud address leads back to this server: relaying would kick out the breezers."""
        _LOGGER.warning("Not relaying breezers to the Atmeex cloud: %s", reason)
        self._relay_to_cloud = False
        for task in self._relay_tasks:
            task.cancel()

    def _is_own_address(self, writer: asyncio.StreamWriter) -> bool:
        """The cloud address leads to this server, as with a DNS override instead of a router rule."""
        peer = writer.get_extra_info("peername")
        return peer[0] == writer.get_extra_info("sockname")[0] and peer[1] == self.port

    async def _async_relay_from_cloud(
        self, session: AtmeexLocalSession, hello: dict, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        _LOGGER.info("Breezer %s connected to the Atmeex cloud through Home Assistant", session.device_id)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""
        relayed_hello = _encode({"id": session.device_id, "hello": hello})
        self._relayed_hellos[relayed_hello] = asyncio.get_running_loop().time()
        try:
            writer.write(relayed_hello)
            session.cloud = writer
            while data := await reader.read(4096):
                messages, buffer = split_messages(buffer + decoder.decode(data))
                if len(buffer) > MAX_BUFFER:
                    break

                for message in messages:
                    # The breezer got its hello reply from Home Assistant already
                    if isinstance(message, dict) and "hello" not in message:
                        await session.async_write(message)
        except OSError as err:
            _LOGGER.debug("Atmeex cloud connection error: %s", err)
        finally:
            self._relayed_hellos.pop(relayed_hello, None)
            session.cloud = None
            writer.close()
            _LOGGER.info("Breezer %s disconnected from the Atmeex cloud", session.device_id)
