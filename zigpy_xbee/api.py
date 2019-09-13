import asyncio
import binascii
import enum
import functools
import logging

from zigpy.exceptions import DeliveryError
from zigpy.types import LVList

from . import uart
from . import types as t

LOGGER = logging.getLogger(__name__)

AT_COMMAND_TIMEOUT = 2
REMOTE_AT_COMMAND_TIMEOUT = 30


class ModemStatus(t.uint8_t, t.UndefinedEnum):
    HARDWARE_RESET = 0x00
    WATCHDOG_TIMER_RESET = 0x01
    JOINED_NETWORK = 0x02
    DISASSOCIATED = 0x03
    COORDINATOR_STARTED = 0x06
    NETWORK_SECURITY_KEY_UPDATED = 0x07
    VOLTAGE_SUPPLY_LIMIT_EXCEEDED = 0x0D
    MODEM_CONFIGURATION_CHANGED_WHILE_JOIN_IN_PROGRESS = 0x11

    UNKNOWN_MODEM_STATUS = 0xFF
    _UNDEFINED = 0xFF


# https://www.digi.com/resources/documentation/digidocs/PDFs/90000976.pdf
COMMAND_REQUESTS = {
    "at": (0x08, (t.FrameId, t.ATCommand, t.Bytes), 0x88),
    "queued_at": (0x09, (t.FrameId, t.ATCommand, t.Bytes), 0x88),
    "remote_at": (
        0x17,
        (t.FrameId, t.EUI64, t.NWK, t.uint8_t, t.ATCommand, t.Bytes),
        0x97,
    ),
    "tx": (0x10, (), None),
    "tx_explicit": (
        0x11,
        (
            t.FrameId,
            t.EUI64,
            t.NWK,
            t.uint8_t,
            t.uint8_t,
            t.uint16_t,
            t.uint16_t,
            t.uint8_t,
            t.uint8_t,
            t.Bytes,
        ),
        0x8B,
    ),
    "create_source_route": (
        0x21,
        (t.FrameId, t.EUI64, t.NWK, t.uint8_t, LVList(t.NWK)),
        None,
    ),
    "register_joining_device": (0x24, (), None),
}
COMMAND_RESPONSES = {
    "at_response": (0x88, (t.FrameId, t.ATCommand, t.uint8_t, t.Bytes), None),
    "modem_status": (0x8A, (ModemStatus,), None),
    "tx_status": (
        0x8B,
        (t.FrameId, t.NWK, t.uint8_t, t.TXStatus, t.DiscoveryStatus),
        None,
    ),
    "route_information": (0x8D, (), None),
    "rx": (0x90, (), None),
    "explicit_rx_indicator": (
        0x91,
        (
            t.EUI64,
            t.NWK,
            t.uint8_t,
            t.uint8_t,
            t.uint16_t,
            t.uint16_t,
            t.uint8_t,
            t.Bytes,
        ),
        None,
    ),
    "rx_io_data_long_addr": (0x92, (), None),
    "remote_at_response": (
        0x97,
        (t.FrameId, t.EUI64, t.NWK, t.ATCommand, t.uint8_t, t.Bytes),
        None,
    ),
    "extended_status": (0x98, (), None),
    "route_record_indicator": (0xA1, (t.EUI64, t.NWK, t.uint8_t, LVList(t.NWK)), None),
    "many_to_one_rri": (0xA3, (t.EUI64, t.NWK, t.uint8_t), None),
    "node_id_indicator": (0x95, (), None),
}

# https://www.digi.com/resources/documentation/digidocs/PDFs/90000976.pdf pg 157
AT_COMMANDS = {
    # Addressing commands
    "DH": t.uint32_t,
    "DL": t.uint32_t,
    "MY": t.uint16_t,
    "MP": t.uint16_t,
    "NC": t.uint32_t,  # 0 - MAX_CHILDREN.
    "SH": t.uint32_t,
    "SL": t.uint32_t,
    "NI": t,  # 20 byte printable ascii string
    "SE": t.uint8_t,
    "DE": t.uint8_t,
    "CI": t.uint16_t,
    "TO": t.uint8_t,
    "NP": t.uint16_t,
    "DD": t.uint32_t,
    "CR": t.uint8_t,  # 0 - 0x3F
    # Networking commands
    "CH": t.uint8_t,  # 0x0B - 0x1A
    "DA": t,  # no param
    "ID": t.uint64_t,
    "OP": t.uint64_t,
    "NH": t.uint8_t,
    "BH": t.uint8_t,  # 0 - 0x1E
    "OI": t.uint16_t,
    "NT": t.uint8_t,  # 0x20 - 0xFF
    "NO": t.uint8_t,  # bitfield, 0 - 3
    "SC": t.uint16_t,  # 1 - 0xFFFF
    "SD": t.uint8_t,  # 0 - 7
    "ZS": t.uint8_t,  # 0 - 2
    "NJ": t.uint8_t,
    "JV": t.Bool,
    "NW": t.uint16_t,  # 0 - 0x64FF
    "JN": t.Bool,
    "AR": t.uint8_t,
    "DJ": t.Bool,  # WTF, docs
    "II": t.uint16_t,
    # Security commands
    "EE": t.Bool,
    "EO": t.uint8_t,
    "NK": t.Bytes,  # 128-bit value
    "KY": t.Bytes,  # 128-bit value
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
    "D7": t.uint8_t,  # 0 - 7 (an Enum)
    "D6": t.uint8_t,  # 0 - 5 (an Enum)
    # I/O commands
    "IR": t.uint16_t,
    "IC": t.uint16_t,
    "P0": t.uint8_t,  # 0 - 5 (an Enum)
    "P1": t.uint8_t,  # 0 - 5 (an Enum)
    "P2": t.uint8_t,  # 0 - 5 (an Enum)
    "P3": t.uint8_t,  # 0 - 5 (an Enum)
    "D0": t.uint8_t,  # 0 - 5 (an Enum)
    "D1": t.uint8_t,  # 0 - 5 (an Enum)
    "D2": t.uint8_t,  # 0 - 5 (an Enum)
    "D3": t.uint8_t,  # 0 - 5 (an Enum)
    "D4": t.uint8_t,  # 0 - 5 (an Enum)
    "D5": t.uint8_t,  # 0 - 5 (an Enum)
    "D8": t.uint8_t,  # 0 - 5 (an Enum)
    "LT": t.uint8_t,
    "PR": t.uint16_t,
    "RP": t.uint8_t,
    "%V": t.uint16_t,  # read only
    "V+": t.uint16_t,
    "TP": t.uint16_t,
    # Diagnostics commands
    "VR": t.uint16_t,
    "HV": t.uint16_t,
    "AI": t.uint8_t,
    # AT command options
    "CT": t.uint16_t,  # 2 - 0x028F
    "CN": None,
    "GT": t.uint16_t,
    "CC": t.uint8_t,
    # Sleep commands
    "SM": t.uint8_t,
    "SN": t.uint16_t,
    "SP": t.uint16_t,
    "ST": t.uint16_t,
    "SO": t.uint8_t,
    "WH": t.uint16_t,
    "SI": None,
    "PO": t.uint16_t,  # 0 - 0x3E8
    # Execution commands
    "AC": None,
    "WR": None,
    "RE": None,
    "FR": None,
    "NR": t.Bool,
    "SI": None,
    "CB": t.uint8_t,
    "ND": t,  # "optional 2-Byte NI value"
    "DN": t.Bytes,  # "up to 20-Byte printable ASCII string"
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


class ATCommandResult(enum.IntEnum):
    OK = 0
    ERROR = 1
    INVALID_COMMAND = 2
    INVALID_PARAMETER = 3
    TX_FAILURE = 4


class XBee:
    def __init__(self):
        self._uart = None
        self._seq = 1
        self._commands_by_id = {v[0]: k for k, v in COMMAND_RESPONSES.items()}
        self._awaiting = {}
        self._app = None
        self._cmd_mode_future = None
        self._reset = asyncio.Event()
        self._running = asyncio.Event()

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

    async def connect(self, device, baudrate=115200):
        assert self._uart is None
        self._uart = await uart.connect(device, baudrate, self)

    def close(self):
        return self._uart.close()

    def _command(self, name, *args, mask_frame_id=False):
        LOGGER.debug("Command %s %s", name, args)
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
        c = COMMAND_REQUESTS[name]
        return (bytes([c[0]]) + t.serialize(args, c[1])), c[2]

    def frame_received(self, data):
        command = self._commands_by_id[data[0]]
        LOGGER.debug("Frame received: %s", command)
        data, rest = t.deserialize(data[1:], COMMAND_RESPONSES[command][1])
        try:
            getattr(self, "_handle_%s" % (command,))(*data)
        except AttributeError:
            LOGGER.error("No '%s' handler. Data: %s", command, binascii.hexlify(data))

    def _handle_at_response(self, frame_id, cmd, status, value):
        fut, = self._awaiting.pop(frame_id)
        try:
            status = ATCommandResult(status)
        except ValueError:
            status = ATCommandResult.ERROR

        if status:
            fut.set_exception(
                RuntimeError("AT Command response: {}".format(status.name))
            )
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
        if status == ModemStatus.COORDINATOR_STARTED:
            self.coordinator_started_event.set()
        elif status in (ModemStatus.HARDWARE_RESET, ModemStatus.WATCHDOG_TIMER_RESET):
            self.reset_event.set()
            self.coordinator_started_event.clear()
        elif status == ModemStatus.DISASSOCIATED:
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
            fut, = self._awaiting.pop(frame_id)
        except KeyError:
            LOGGER.debug("unexpected tx_status report received")
            return

        try:
            if tx_status in (
                t.TXStatus.BROADCAST_APS_TX_ATTEMPT,
                t.TXStatus.SELF_ADDRESSED,
                t.TXStatus.SUCCESS,
            ):
                fut.set_result(tx_status)
            else:
                fut.set_exception(DeliveryError("%s" % (tx_status,)))
        except asyncio.InvalidStateError as ex:
            LOGGER.debug("duplicate tx_status for %s nwk? State: %s", nwk, ex)

    def set_application(self, app):
        self._app = app

    def handle_command_mode_rsp(self, data):
        """Handle AT command response in command mode."""
        fut = self._cmd_mode_future
        if fut is None or fut.done():
            return
        if data == "OK":
            fut.set_result(True)
        elif data == "ERROR":
            fut.set_result(False)
        else:
            fut.set_result(data)

    async def command_mode_at_cmd(self, command):
        """Sends AT command in command mode."""
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
            if await self.command_mode_at_cmd(cmd + "\r"):
                LOGGER.debug("Successfuly sent %s cmd", cmd)
            else:
                LOGGER.debug("No response to %s cmd", cmd)
                return None
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
            (
                "Couldn't enter AT command mode at any known baudrate."
                "Configure XBee manually for escaped API mode ATAP2"
            )
        )
        return False

    def __getattr__(self, item):
        if item in COMMAND_REQUESTS:
            return functools.partial(self._command, item)
        raise AttributeError("Unknown command {}".format(item))
