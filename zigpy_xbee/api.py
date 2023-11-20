"""XBee API implementation."""

import asyncio
import binascii
import functools
import logging
from typing import Any, Dict, Optional

import serial
from zigpy.config import CONF_DEVICE_PATH, SCHEMA_DEVICE
from zigpy.exceptions import APIException, DeliveryError
import zigpy.types as t

import zigpy_xbee
from zigpy_xbee.exceptions import (
    ATCommandError,
    ATCommandException,
    InvalidCommand,
    InvalidParameter,
    TransmissionFailure,
)

from . import types as xbee_t, uart

LOGGER = logging.getLogger(__name__)

AT_COMMAND_TIMEOUT = 3
REMOTE_AT_COMMAND_TIMEOUT = 30
PROBE_TIMEOUT = 45


# https://www.digi.com/resources/documentation/digidocs/PDFs/90000976.pdf
COMMAND_REQUESTS = {
    "at": (0x08, (xbee_t.FrameId, xbee_t.ATCommand, xbee_t.Bytes), 0x88),
    "queued_at": (0x09, (xbee_t.FrameId, xbee_t.ATCommand, xbee_t.Bytes), 0x88),
    "remote_at": (
        0x17,
        (
            xbee_t.FrameId,
            xbee_t.EUI64,
            xbee_t.NWK,
            t.uint8_t,
            xbee_t.ATCommand,
            xbee_t.Bytes,
        ),
        0x97,
    ),
    "tx": (0x10, (), None),
    "tx_explicit": (
        0x11,
        (
            xbee_t.FrameId,
            xbee_t.EUI64,
            xbee_t.NWK,
            t.uint8_t,
            t.uint8_t,
            t.uint16_t_be,
            t.uint16_t_be,
            t.uint8_t,
            t.uint8_t,
            xbee_t.Bytes,
        ),
        0x8B,
    ),
    "create_source_route": (
        0x21,
        (xbee_t.FrameId, xbee_t.EUI64, xbee_t.NWK, t.uint8_t, xbee_t.Relays),
        None,
    ),
    "register_joining_device": (
        0x24,
        (xbee_t.FrameId, xbee_t.EUI64, t.uint16_t_be, t.uint8_t, xbee_t.Bytes),
        0xA4,
    ),
}
COMMAND_RESPONSES = {
    "at_response": (
        0x88,
        (xbee_t.FrameId, xbee_t.ATCommand, t.uint8_t, xbee_t.Bytes),
        None,
    ),
    "modem_status": (0x8A, (xbee_t.ModemStatus,), None),
    "tx_status": (
        0x8B,
        (
            xbee_t.FrameId,
            xbee_t.NWK,
            t.uint8_t,
            xbee_t.TXStatus,
            xbee_t.DiscoveryStatus,
        ),
        None,
    ),
    "route_information": (0x8D, (), None),
    "rx": (0x90, (), None),
    "explicit_rx_indicator": (
        0x91,
        (
            xbee_t.EUI64,
            xbee_t.NWK,
            t.uint8_t,
            t.uint8_t,
            t.uint16_t_be,
            t.uint16_t_be,
            t.uint8_t,
            xbee_t.Bytes,
        ),
        None,
    ),
    "rx_io_data_long_addr": (0x92, (), None),
    "remote_at_response": (
        0x97,
        (
            xbee_t.FrameId,
            xbee_t.EUI64,
            xbee_t.NWK,
            xbee_t.ATCommand,
            t.uint8_t,
            xbee_t.Bytes,
        ),
        None,
    ),
    "extended_status": (0x98, (), None),
    "route_record_indicator": (
        0xA1,
        (xbee_t.EUI64, xbee_t.NWK, t.uint8_t, xbee_t.Relays),
        None,
    ),
    "many_to_one_rri": (0xA3, (xbee_t.EUI64, xbee_t.NWK, t.uint8_t), None),
    "registration_status": (0xA4, (xbee_t.FrameId, xbee_t.RegistrationStatus), None),
    "node_id_indicator": (0x95, (), None),
}

# https://www.digi.com/resources/documentation/digidocs/pdfs/90001539.pdf pg 175
AT_COMMANDS = {
    # Addressing commands
    "DH": t.uint32_t_be,
    "DL": t.uint32_t_be,
    "MY": t.uint16_t_be,
    "MP": t.uint16_t_be,
    "NC": t.uint32_t_be,  # 0 - MAX_CHILDREN.
    "SH": t.uint32_t_be,
    "SL": t.uint32_t_be,
    "NI": t,  # 20 byte printable ascii string
    "SE": t.uint8_t,
    "DE": t.uint8_t,
    "CI": t.uint16_t_be,
    "TO": t.uint8_t,
    "NP": t.uint16_t_be,
    "DD": t.uint32_t_be,
    "CR": t.uint8_t,  # 0 - 0x3F
    # Networking commands
    "CH": t.uint8_t,  # 0x0B - 0x1A
    "DA": t,  # no param
    "ID": t.uint64_t_be,
    "OP": t.uint64_t_be,
    "NH": t.uint8_t,
    "BH": t.uint8_t,  # 0 - 0x1E
    "OI": t.uint16_t_be,
    "NT": t.uint8_t,  # 0x20 - 0xFF
    "NO": t.uint8_t,  # bitfield, 0 - 3
    "SC": t.uint16_t_be,  # 1 - 0xFFFF
    "SD": t.uint8_t,  # 0 - 7
    "ZS": t.uint8_t,  # 0 - 2
    "NJ": t.uint8_t,
    "JV": t.Bool,
    "NW": t.uint16_t_be,  # 0 - 0x64FF
    "JN": t.Bool,
    "AR": t.uint8_t,
    "DJ": t.Bool,  # WTF, docs
    "II": t.uint16_t_be,
    # Security commands
    "EE": t.Bool,
    "EO": t.uint8_t,
    "NK": xbee_t.Bytes,  # 128-bit value
    "KY": xbee_t.Bytes,  # 128-bit value
    "KT": t.uint16_t_be,  # 0x1E - 0xFFFF
    # RF interfacing commands
    "PL": t.uint8_t,  # 0 - 4 (basically an Enum)
    "PM": t.Bool,
    "DB": t.uint8_t,
    "PP": t.uint8_t,  # RO
    "AP": t.uint8_t,  # 1-2 (an Enum)
    "AO": t.uint8_t,  # 0 - 3 (an Enum)
    "BD": t.uint8_t,  # 0 - 7 (an Enum)
    "NB": t.uint8_t,  # 0 - 3 (an Enum)
    "SB": t.uint8_t,  # 0 - 1 (an Enum)
    "RO": t.uint8_t,
    "D6": t.uint8_t,  # 0 - 5 (an Enum)
    "D7": t.uint8_t,  # 0 - 7 (an Enum)
    "P3": t.uint8_t,  # 0 - 5 (an Enum)
    "P4": t.uint8_t,  # 0 - 5 (an Enum)
    # MAC diagnostics commands
    "ED": xbee_t.Bytes,  # 16-byte value
    # I/O commands
    "IR": t.uint16_t_be,
    "IC": t.uint16_t_be,
    "D0": t.uint8_t,  # 0 - 5 (an Enum)
    "D1": t.uint8_t,  # 0 - 5 (an Enum)
    "D2": t.uint8_t,  # 0 - 5 (an Enum)
    "D3": t.uint8_t,  # 0 - 5 (an Enum)
    "D4": t.uint8_t,  # 0 - 5 (an Enum)
    "D5": t.uint8_t,  # 0 - 5 (an Enum)
    "D8": t.uint8_t,  # 0 - 5 (an Enum)
    "D9": t.uint8_t,  # 0 - 5 (an Enum)
    "P0": t.uint8_t,  # 0 - 5 (an Enum)
    "P1": t.uint8_t,  # 0 - 5 (an Enum)
    "P2": t.uint8_t,  # 0 - 5 (an Enum)
    "P5": t.uint8_t,  # 0 - 5 (an Enum)
    "P6": t.uint8_t,  # 0 - 5 (an Enum)
    "P7": t.uint8_t,  # 0 - 5 (an Enum)
    "P8": t.uint8_t,  # 0 - 5 (an Enum)
    "P9": t.uint8_t,  # 0 - 5 (an Enum)
    "LT": t.uint8_t,
    "PR": t.uint16_t_be,
    "RP": t.uint8_t,
    "%V": t.uint16_t_be,  # read only
    "V+": t.uint16_t_be,
    "TP": t.uint16_t_be,
    "M0": t.uint16_t_be,  # 0 - 0x3FF
    "M1": t.uint16_t_be,  # 0 - 0x3FF
    # Diagnostics commands
    "VR": t.uint16_t_be,
    "HV": t.uint16_t_be,
    "AI": t.uint8_t,
    # AT command options
    "CT": t.uint16_t_be,  # 2 - 0x028F
    "CN": None,
    "GT": t.uint16_t_be,
    "CC": t.uint8_t,
    # Sleep commands
    "SM": t.uint8_t,
    "SN": t.uint16_t_be,
    "SP": t.uint16_t_be,
    "ST": t.uint16_t_be,
    "SO": t.uint8_t,
    "WH": t.uint16_t_be,
    "SI": None,
    "PO": t.uint16_t_be,  # 0 - 0x3E8
    # Execution commands
    "AC": None,
    "WR": None,
    "RE": None,
    "FR": None,
    "NR": t.Bool,
    "CB": t.uint8_t,
    "ND": t,  # "optional 2-Byte NI value"
    "DN": xbee_t.Bytes,  # "up to 20-Byte printable ASCII string"
    "IS": None,
    "1S": None,
    "AS": None,
    # Stuff I've guessed
    "CE": t.uint8_t,
}


BAUDRATE_TO_BD = {
    1200: "ATBD0",
    2400: "ATBD1",
    4800: "ATBD2",
    9600: "ATBD3",
    19200: "ATBD4",
    38400: "ATBD5",
    57600: "ATBD6",
    115200: "ATBD7",
    230400: "ATBD8",
}


AT_COMMAND_RESULT = {
    1: ATCommandError,
    2: InvalidCommand,
    3: InvalidParameter,
    4: TransmissionFailure,
}


class XBee:
    """Class implementing XBee communication protocol."""

    def __init__(self, device_config: Dict[str, Any]) -> None:
        """Initialize instance."""
        self._config = device_config
        self._uart: Optional[uart.Gateway] = None
        self._seq: int = 1
        self._commands_by_id = {v[0]: k for k, v in COMMAND_RESPONSES.items()}
        self._awaiting = {}
        self._app = None
        self._cmd_mode_future: Optional[asyncio.Future] = None
        self._reset: asyncio.Event = asyncio.Event()
        self._running: asyncio.Event = asyncio.Event()

    @property
    def reset_event(self):
        """Return reset event."""
        return self._reset

    @property
    def coordinator_started_event(self):
        """Return coordinator started."""
        return self._running

    @property
    def is_running(self):
        """Return true if coordinator is running."""
        return self.coordinator_started_event.is_set()

    @classmethod
    async def new(
        cls,
        application: "zigpy_xbee.zigbee.application.ControllerApplication",
        config: Dict[str, Any],
    ) -> "XBee":
        """Create new instance."""
        xbee_api = cls(config)
        await xbee_api.connect()
        xbee_api.set_application(application)
        return xbee_api

    async def connect(self) -> None:
        """Connect to the device."""
        assert self._uart is None
        self._uart = await uart.connect(self._config, self)

    def connection_lost(self, exc: Exception) -> None:
        """Lost serial connection."""
        if self._app is not None:
            self._app.connection_lost(exc)

    def close(self):
        """Close the connection."""
        if self._uart:
            self._uart.close()
            self._uart = None

    def _command(self, name, *args, mask_frame_id=False):
        """Send API frame to the device."""
        LOGGER.debug("Command %s %s", name, args)
        if self._uart is None:
            raise APIException("API is not running")
        frame_id = 0 if mask_frame_id else self._seq
        data, needs_response = self._api_frame(name, frame_id, *args)
        self._uart.send(data)
        future = None
        if needs_response and frame_id:
            future = asyncio.Future()
            self._awaiting[frame_id] = (future,)
        self._seq = (self._seq % 255) + 1
        return future

    async def _remote_at_command(self, ieee, nwk, options, name, *args):
        """Execute AT command on a different XBee module in the network."""
        LOGGER.debug("Remote AT command: %s %s", name, args)
        data = t.serialize(args, (AT_COMMANDS[name],))
        try:
            return await asyncio.wait_for(
                self._command(
                    "remote_at", ieee, nwk, options, name.encode("ascii"), data
                ),
                timeout=REMOTE_AT_COMMAND_TIMEOUT,
            )
        except asyncio.TimeoutError:
            LOGGER.warning("No response to %s command", name)
            raise

    async def _at_partial(self, cmd_type, name, *args):
        LOGGER.debug("%s command: %s %s", cmd_type, name, args)
        data = t.serialize(args, (AT_COMMANDS[name],))
        try:
            return await asyncio.wait_for(
                self._command(cmd_type, name.encode("ascii"), data),
                timeout=AT_COMMAND_TIMEOUT,
            )
        except asyncio.TimeoutError:
            LOGGER.warning("%s: No response to %s command", cmd_type, name)
            raise

    _at_command = functools.partialmethod(_at_partial, "at")
    _queued_at = functools.partialmethod(_at_partial, "queued_at")

    def _api_frame(self, name, *args):
        """Build API frame."""
        c = COMMAND_REQUESTS[name]
        return (bytes([c[0]]) + t.serialize(args, c[1])), c[2]

    def frame_received(self, data):
        """Handle API frame from the device."""
        command = self._commands_by_id[data[0]]
        LOGGER.debug("Frame received: %s", command)
        data, rest = t.deserialize(data[1:], COMMAND_RESPONSES[command][1])
        try:
            getattr(self, f"_handle_{command}")(*data)
        except AttributeError:
            LOGGER.error("No '%s' handler. Data: %s", command, binascii.hexlify(data))

    def _handle_at_response(self, frame_id, cmd, status, value):
        """Local AT command response."""
        (fut,) = self._awaiting.pop(frame_id)

        if status:
            try:
                exception = AT_COMMAND_RESULT[status]
            except KeyError:
                exception = ATCommandException
            fut.set_exception(exception(f"AT Command response: {status}"))
            return

        response_type = AT_COMMANDS[cmd.decode("ascii")]
        if response_type is None or len(value) == 0:
            fut.set_result(None)
            return

        response, remains = response_type.deserialize(value)
        fut.set_result(response)

    def _handle_remote_at_response(self, frame_id, ieee, nwk, cmd, status, value):
        """Remote AT command response."""
        LOGGER.debug(
            "Remote AT command response from: %s",
            (frame_id, ieee, nwk, cmd, status, value),
        )
        return self._handle_at_response(frame_id, cmd, status, value)

    def _handle_many_to_one_rri(self, ieee, nwk, reserved):
        LOGGER.debug("_handle_many_to_one_rri: %s", (ieee, nwk, reserved))

    def _handle_modem_status(self, status):
        LOGGER.debug("Handle modem status frame: %s", status)
        status = status
        if status == xbee_t.ModemStatus.COORDINATOR_STARTED:
            self.coordinator_started_event.set()
        elif status in (
            xbee_t.ModemStatus.HARDWARE_RESET,
            xbee_t.ModemStatus.WATCHDOG_TIMER_RESET,
        ):
            self.reset_event.set()
            self.coordinator_started_event.clear()
        elif status == xbee_t.ModemStatus.DISASSOCIATED:
            self.coordinator_started_event.clear()

        if self._app:
            self._app.handle_modem_status(status)

    def _handle_explicit_rx_indicator(
        self, ieee, nwk, src_ep, dst_ep, cluster, profile, rx_opts, data
    ):
        LOGGER.debug(
            "_handle_explicit_rx: %s",
            (ieee, nwk, dst_ep, cluster, rx_opts, binascii.hexlify(data)),
        )
        self._app.handle_rx(ieee, nwk, src_ep, dst_ep, cluster, profile, rx_opts, data)

    def _handle_route_record_indicator(self, ieee, src, rx_opts, hops):
        """Handle Route Record indicator from a device."""
        LOGGER.debug("_handle_route_record_indicator: %s", (ieee, src, rx_opts, hops))

    def _handle_tx_status(self, frame_id, nwk, tries, tx_status, dsc_status):
        LOGGER.debug(
            (
                "tx_explicit to 0x%04x: %s after %i tries. Discovery Status: %s,"
                " Frame #%i"
            ),
            nwk,
            tx_status,
            tries,
            dsc_status,
            frame_id,
        )
        try:
            (fut,) = self._awaiting.pop(frame_id)
        except KeyError:
            LOGGER.debug("unexpected tx_status report received")
            return

        try:
            if tx_status in (
                xbee_t.TXStatus.BROADCAST_APS_TX_ATTEMPT,
                xbee_t.TXStatus.SELF_ADDRESSED,
                xbee_t.TXStatus.SUCCESS,
            ):
                fut.set_result(tx_status)
            else:
                fut.set_exception(DeliveryError(f"{tx_status}"))
        except asyncio.InvalidStateError as ex:
            LOGGER.debug("duplicate tx_status for %s nwk? State: %s", nwk, ex)

    def _handle_registration_status(self, frame_id, status):
        (fut,) = self._awaiting.pop(frame_id)
        if status:
            fut.set_exception(RuntimeError(f"Registration Status: {status.name}"))
            return
        LOGGER.debug(f"Registration Status: {status.name}")

        fut.set_result(status)

    def set_application(self, app):
        """Set reference to ControllerApplication."""
        self._app = app

    def handle_command_mode_rsp(self, data):
        """Handle AT command response in command mode."""
        fut = self._cmd_mode_future
        if fut is None or fut.done():
            return
        if "OK" in data:
            fut.set_result(True)
        elif "ERROR" in data:
            fut.set_result(False)
        else:
            fut.set_result(data)

    async def command_mode_at_cmd(self, command):
        """Send AT command in command mode."""
        self._cmd_mode_future = asyncio.Future()
        self._uart.command_mode_send(command.encode("ascii"))

        try:
            res = await asyncio.wait_for(self._cmd_mode_future, timeout=2)
            return res
        except asyncio.TimeoutError:
            LOGGER.debug("Command mode no response to AT '%s' command", command)
            return None

    async def enter_at_command_mode(self):
        """Enter command mode."""
        await asyncio.sleep(1.2)  # keep UART quiet for 1s before escaping
        return await self.command_mode_at_cmd("+++")

    async def api_mode_at_commands(self, baudrate):
        """Configure API and exit AT command mode."""
        cmds = ["ATAP2", "ATWR", "ATCN"]

        bd = BAUDRATE_TO_BD.get(baudrate)
        if bd:
            cmds.insert(0, bd)

        for cmd in cmds:
            if not await self.command_mode_at_cmd(cmd + "\r"):
                LOGGER.debug("No response to %s cmd", cmd)
                return None
            LOGGER.debug("Successfully sent %s cmd", cmd)
        self._uart.reset_command_mode()
        return True

    async def init_api_mode(self):
        """Configure API mode on XBee."""
        current_baudrate = self._uart.baudrate
        if await self.enter_at_command_mode():
            LOGGER.debug("Entered AT Command mode at %dbps.", self._uart.baudrate)
            return await self.api_mode_at_commands(current_baudrate)

        for baudrate in sorted(BAUDRATE_TO_BD.keys()):
            LOGGER.debug(
                "Failed to enter AT command mode at %dbps, trying %d next",
                self._uart.baudrate,
                baudrate,
            )
            self._uart.baudrate = baudrate
            if await self.enter_at_command_mode():
                LOGGER.debug("Entered AT Command mode at %dbps.", self._uart.baudrate)
                res = await self.api_mode_at_commands(current_baudrate)
                self._uart.baudrate = current_baudrate
                return res

        LOGGER.debug(
            "Couldn't enter AT command mode at any known baudrate."
            "Configure XBee manually for escaped API mode ATAP2"
        )
        return False

    @classmethod
    async def probe(cls, device_config: Dict[str, Any]) -> bool:
        """Probe port for the device presence."""
        api = cls(SCHEMA_DEVICE(device_config))
        try:
            await asyncio.wait_for(api._probe(), timeout=PROBE_TIMEOUT)
            return True
        except (asyncio.TimeoutError, serial.SerialException, APIException) as exc:
            LOGGER.debug(
                "Unsuccessful radio probe of '%s' port",
                device_config[CONF_DEVICE_PATH],
                exc_info=exc,
            )
        finally:
            api.close()

        return False

    async def _probe(self) -> None:
        """Open port and try sending a command."""
        await self.connect()
        try:
            # Ensure we have escaped commands
            await self._at_command("AP", 2)
        except asyncio.TimeoutError:
            if not await self.init_api_mode():
                raise APIException("Failed to configure XBee for API mode")
        finally:
            self.close()

    def __getattr__(self, item):
        """Handle supported command requests."""
        if item in COMMAND_REQUESTS:
            return functools.partial(self._command, item)
        raise AttributeError(f"Unknown command {item}")
