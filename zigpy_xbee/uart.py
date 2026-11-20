"""Module for UART communication to the device."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

import zigpy.config
import zigpy.serial

if TYPE_CHECKING:
    from zigpy_xbee.api import XBee

LOGGER = logging.getLogger(__name__)


class Gateway(zigpy.serial.SerialProtocol):
    """Class implementing the UART protocol."""

    START = b"\x7e"
    ESCAPE = b"\x7d"
    XON = b"\x11"
    XOFF = b"\x13"

    RESERVED = START + ESCAPE + XON + XOFF
    THIS_ONE = True

    # Standard baudrates, previously sourced from the underlying serial library.
    # zigpy now uses `serialx`, which does not expose a `BAUDRATES` attribute, so
    # the list is kept here to avoid depending on the serial backend.
    BAUDRATES = (
        50,
        75,
        110,
        134,
        150,
        200,
        300,
        600,
        1200,
        1800,
        2400,
        4800,
        9600,
        19200,
        38400,
        57600,
        115200,
        230400,
        460800,
        500000,
        576000,
        921600,
        1000000,
        1152000,
        1500000,
        2000000,
        2500000,
        3000000,
        3500000,
        4000000,
    )

    def __init__(self, api: XBee) -> None:
        """Initialize instance."""
        super().__init__()
        self._api = api
        self._in_command_mode = False

    def send(self, data: bytes) -> None:
        """Send data, taking care of escaping and framing."""
        LOGGER.debug("Sending: %s", data)
        checksum = bytes([self._checksum(data)])
        frame = self.START + self._escape(
            len(data).to_bytes(2, "big") + data + checksum
        )
        assert self._transport is not None
        self._transport.write(frame)

    @property
    def baudrate(self) -> int:
        """Baudrate."""
        assert self._transport is not None
        return self._transport.serial.baudrate

    @baudrate.setter
    def baudrate(self, baudrate: int) -> None:
        """Set baudrate."""
        if baudrate in self.BAUDRATES:
            assert self._transport is not None
            self._transport.serial.baudrate = baudrate
        else:
            raise ValueError(f"baudrate must be one of {self.BAUDRATES}")

    def connection_lost(self, exc: BaseException | None) -> None:
        """Port was closed expectedly or unexpectedly."""
        super().connection_lost(exc)

        if self._api is not None:
            self._api.connection_lost(exc)

    def command_mode_rsp(self, data: bytes | bytearray) -> None:
        """Handle AT command mode response."""
        rsp = data.decode("ascii", "ignore")
        LOGGER.debug("Handling AT command mode response: %s", rsp)
        self._api.handle_command_mode_rsp(rsp)

    def command_mode_send(self, data: bytes) -> None:
        """Send data in command mode."""
        LOGGER.debug("Command mode sending %s to uart", data)
        self._in_command_mode = True
        assert self._transport is not None
        self._transport.write(data)

    def data_received(self, data: bytes) -> None:
        """Handle data received from the UART callback."""
        super().data_received(data)
        while self._buffer:
            frame = self._extract_frame()
            if frame is None:
                break
            self.frame_received(frame)
        if self._in_command_mode and self._buffer[-1:] == b"\r":
            rsp = self._buffer[:-1]
            self._buffer.clear()
            self.command_mode_rsp(rsp)

    def frame_received(self, frame: bytes) -> None:
        """Frame receive handler."""
        LOGGER.debug("Frame received: %s", frame)
        self._api.frame_received(frame)

    def reset_command_mode(self) -> None:
        r"""Reset command mode and ignore '\r' character as command mode response."""
        self._in_command_mode = False

    def _extract_frame(self) -> bytes | None:
        first_start = self._buffer.find(self.START)
        if first_start < 0:
            return None

        frame_len, data = self._get_unescaped(self._buffer[first_start + 1 :], 2)
        if frame_len is None:
            return None
        assert data is not None

        frame, data = self._get_unescaped(data, int.from_bytes(frame_len, "big"))
        if frame is None:
            return None
        assert data is not None
        checksum, data = self._get_unescaped(data, 1)
        if checksum is None:
            return None
        assert data is not None
        if self._checksum(frame) != checksum[0]:
            # TODO: Signal decode failure so that error frame can be sent
            self._buffer = data
            return None

        self._buffer = data
        return frame

    def _get_unescaped(
        self, data: bytearray, n: int
    ) -> tuple[bytes, bytearray] | tuple[None, None]:
        ret: list[int] = []
        idx = 0
        while len(ret) < n and idx < len(data):
            b = data[idx]
            if b == self.ESCAPE[0]:
                idx += 1
                if idx >= len(data):
                    return None, None
                b = data[idx] ^ 0x020
            ret.append(b)
            idx += 1

        if len(ret) >= n:
            return bytes(ret), data[idx:]
        return None, None

    def _escape(self, data: bytes) -> bytes:
        ret: list[int] = []
        for b in data:
            if b in self.RESERVED:
                ret.append(ord(self.ESCAPE))
                ret.append(b ^ 0x20)
            else:
                ret.append(b)
        return bytes(ret)

    def _checksum(self, data: bytes) -> int:
        return 0xFF - (sum(data) % 0x100)


async def connect(device_config: dict[str, Any], api: XBee) -> Gateway:
    """Connect to the device."""
    transport, protocol = await zigpy.serial.create_serial_connection(
        loop=asyncio.get_running_loop(),
        protocol_factory=lambda: Gateway(api),
        url=device_config[zigpy.config.CONF_DEVICE_PATH],
        baudrate=device_config[zigpy.config.CONF_DEVICE_BAUDRATE],
        xonxoff=device_config[zigpy.config.CONF_DEVICE_BAUDRATE],
    )

    # `protocol_factory` above only creates `Gateway` instances
    gateway = cast(Gateway, protocol)
    await gateway.wait_until_connected()

    return gateway
