import asyncio
import logging
import serial

import serial_asyncio

LOGGER = logging.getLogger(__name__)


class Gateway(asyncio.Protocol):
    START = b"\x7E"
    ESCAPE = b"\x7D"
    XON = b"\x11"
    XOFF = b"\x13"

    RESERVED = START + ESCAPE + XON + XOFF

    def __init__(self, api, connected_future=None):
        self._buffer = b""
        self._connected_future = connected_future
        self._api = api
        self._in_command_mode = False

    def send(self, data):
        """Send data, taking care of escaping and framing"""
        LOGGER.debug("Sending: %s", data)
        checksum = bytes([self._checksum(data)])
        frame = self.START + self._escape(
            len(data).to_bytes(2, "big") + data + checksum
        )
        self._transport.write(frame)

    @property
    def baudrate(self):
        """Baudrate."""
        return self._transport.serial.baudrate

    @baudrate.setter
    def baudrate(self, baudrate):
        """Set baudrate."""
        if baudrate in self._transport.serial.BAUDRATES:
            self._transport.serial.baudrate = baudrate
        else:
            raise ValueError(
                "baudrate must be one of {}".format(self._transport.serial.BAUDRATES)
            )

    def connection_made(self, transport):
        """Callback when the uart is connected"""
        LOGGER.debug("Connection made")
        self._transport = transport
        if self._connected_future:
            self._connected_future.set_result(True)

    def command_mode_rsp(self, data):
        """Handles AT command mode response."""
        try:
            data = data.decode("ascii")
        except UnicodeDecodeError as ex:
            LOGGER.debug("Couldn't ascii decode AT command mode response: %s", ex)
            raise
        LOGGER.debug("Handling AT command mode response: %s", data)
        self._api.handle_command_mode_rsp(data)

    def command_mode_send(self, data):
        """Send data in command mode."""
        LOGGER.debug("Command mode sending %s to uart", data)
        self._in_command_mode = True
        self._transport.write(data)

    def data_received(self, data):
        """Callback when there is data received from the uart"""
        self._buffer += data
        while self._buffer:
            frame = self._extract_frame()
            if frame is None:
                break
            self.frame_received(frame)
        if self._in_command_mode and self._buffer[-1:] == b"\r":
            rsp, self._buffer = (self._buffer[:-1], b"")
            self.command_mode_rsp(rsp)

    def frame_received(self, frame):
        """Frame receive handler"""
        LOGGER.debug("Frame received: %s", frame)
        self._api.frame_received(frame)

    def close(self):
        self._transport.close()

    def reset_command_mode(self):
        """Reset command mode and ignore \r character as command mode response."""
        self._in_command_mode = False

    def _extract_frame(self):
        first_start = self._buffer.find(self.START)
        if first_start < 0:
            return None

        data = self._buffer[first_start + 1 :]
        frame_len, data = self._get_unescaped(data, 2)
        if frame_len is None:
            return None

        frame_len = int.from_bytes(frame_len, "big")
        frame, data = self._get_unescaped(data, frame_len)
        if frame is None:
            return None
        checksum, data = self._get_unescaped(data, 1)
        if checksum is None:
            return None
        if self._checksum(frame) != checksum[0]:
            # TODO: Signal decode failure so that error frame can be sent
            self._buffer = data
            return None

        self._buffer = data
        return frame

    def _get_unescaped(self, data, n):
        ret = []
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

    def _escape(self, data):
        ret = []
        for b in data:
            if b in self.RESERVED:
                ret.append(ord(self.ESCAPE))
                ret.append(b ^ 0x20)
            else:
                ret.append(b)
        return bytes(ret)

    def _checksum(self, data):
        return 0xFF - (sum(data) % 0x100)


async def connect(port, baudrate, api, loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()

    connected_future = asyncio.Future()
    protocol = Gateway(api, connected_future)

    transport, protocol = await serial_asyncio.create_serial_connection(
        loop,
        lambda: protocol,
        url=port,
        baudrate=baudrate,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=False,
    )

    await connected_future

    return protocol
