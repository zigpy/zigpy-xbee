import asyncio
import logging

from . import uart
from . import types as t

LOGGER = logging.getLogger(__name__)


# https://www.digi.com/resources/documentation/digidocs/PDFs/90000976.pdf
COMMANDS = {
    'at': (0x08, (t.uint8_t, t.ATCommand, t.Bytes), 0x88),
    'queued_at': (0x09, (), None),
    'remote_at': (0x17, (), None),
    'tx': (0x10, (), None),
    'tx_explicit': (0x11, (t.uint8_t, t.EUI64, t.uint16_t, t.uint8_t, t.uint8_t, t.uint16_t, t.uint16_t, t.uint8_t, t.uint8_t, t.Bytes), None),
    'create_source_route': (0x21, (), None),
    'register_joining_device': (0x24, (), None),

    'at_response': (0x88, (t.uint8_t, t.ATCommand, t.uint8_t, t.Bytes), None),
    'modem_status': (0x8A, (t.uint8_t, ), None),
    'tx_status': (0x8B, (t.uint8_t, t.uint16_t, t.uint8_t, t.uint8_t, t.uint8_t), None),
    'route_information': (0x8D, (), None),
    'rx': (0x90, (), None),
    'explicit_rx_indicator': (0x91, (t.EUI64, t.uint16_t, t.uint8_t, t.uint8_t, t.uint16_t, t.uint16_t, t.uint8_t, t.Bytes), None),
    'rx_io_data_long_addr': (0x92, (), None),
    'remote_at_response': (0x97, (), None),
    'extended_status': (0x98, (), None),
    'route_record_indicator': (0xA1, (), None),
    'many_to_one_rri': (0xA3, (), None),
    'node_id_indicator': (0x95, (), None),

}

# https://www.digi.com/resources/documentation/digidocs/PDFs/90000976.pdf pg 157
AT_COMMANDS = {
    # Addressing commands
    'DH': t.uint32_t,
    'DL': t.uint32_t,
    'MY': t.uint16_t,
    'MP': t.uint16_t,
    'NC': t.uint32_t,  # 0 - MAX_CHILDREN.
    'SH': t.uint32_t,
    'SL': t.uint32_t,
    'NI': t,  # 20 byte printable ascii string
    'SE': t.uint8_t,
    'DE': t.uint8_t,
    'CI': t.uint16_t,
    'TO': t.uint8_t,
    'NP': t.uint16_t,
    'DD': t.uint32_t,
    'CR': t.uint8_t,  # 0 - 0x3F
    # Networking commands
    'CH': t.uint8_t,  # 0x0B - 0x1A
    'DA': t,  # no param
    'ID': t.uint64_t,
    'OP': t.uint64_t,
    'NH': t.uint8_t,
    'BH': t.uint8_t,  # 0 - 0x1E
    'OI': t.uint16_t,
    'NT': t.uint8_t,  # 0x20 - 0xFF
    'NO': t.uint8_t,  # bitfield, 0 - 3
    'SC': t.uint16_t,  # 1 - 0xFFFF
    'SD': t.uint8_t,  # 0 - 7
    'ZS': t.uint8_t,  # 0 - 2
    'NJ': t.uint8_t,
    'JV': t.Bool,
    'NW': t.uint16_t,  # 0 - 0x64FF
    'JN': t.Bool,
    'AR': t.uint8_t,
    'DJ': t.Bool,  # WTF, docs
    'II': t.uint16_t,
    # Security commands
    'EE': t.Bool,
    'EO': t.uint8_t,
    'NK': t.Bytes,  # 128-bit value
    'KY': t.Bytes,  # 128-bit value
    # RF interfacing commands
    'PL': t.uint8_t,  # 0 - 4 (basically an Enum)
    'PM': t.Bool,
    'DB': t.uint8_t,
    'PP': t.uint8_t,  # RO
    'AP': t.uint8_t,  # 1-2 (an Enum)
    'AO': t.uint8_t,  # 0 - 3 (an Enum)
    'BD': t.uint8_t,  # 0 - 7 (an Enum)
    'NB': t.uint8_t,  # 0 - 3 (an Enum)
    'SB': t.uint8_t,  # 0 - 1 (an Enum)
    'RO': t.uint8_t,
    'D7': t.uint8_t,  # 0 - 7 (an Enum)
    'D6': t.uint8_t,  # 0 - 5 (an Enum)
    # I/O commands
    'IR': t.uint16_t,
    'IC': t.uint16_t,
    'P0': t.uint8_t,  # 0 - 5 (an Enum)
    'P1': t.uint8_t,  # 0 - 5 (an Enum)

    'P2': t.uint8_t,  # 0 - 5 (an Enum)
    'P3': t.uint8_t,  # 0 - 5 (an Enum)
    'D0': t.uint8_t,  # 0 - 5 (an Enum)
    'D1': t.uint8_t,  # 0 - 5 (an Enum)
    'D2': t.uint8_t,  # 0 - 5 (an Enum)
    'D3': t.uint8_t,  # 0 - 5 (an Enum)
    'D4': t.uint8_t,  # 0 - 5 (an Enum)
    'D5': t.uint8_t,  # 0 - 5 (an Enum)
    'D8': t.uint8_t,  # 0 - 5 (an Enum)
    'LT': t.uint8_t,
    'PR': t.uint16_t,
    'RP': t.uint8_t,
    '%V': t.uint16_t,  # read only
    'V+': t.uint16_t,
    'TP': t.uint16_t,
    # Diagnostics commands
    'VR': t.uint16_t,
    'HV': t.uint16_t,
    'AI': t.uint8_t,
    # AT command options
    'CT': t.uint16_t,  # 2 - 0x028F
    'CN': None,
    'GT': t.uint16_t,
    'CC': t.uint8_t,
    # Sleep commands
    'SM': t.uint8_t,
    'SN': t.uint16_t,
    'SP': t.uint16_t,
    'ST': t.uint16_t,
    'SO': t.uint8_t,
    'WH': t.uint16_t,
    'SI': None,
    'PO': t.uint16_t,  # 0 - 0x3E8
    # Execution commands
    'AC': None,
    'WR': None,
    'RE': None,
    'FR': None,
    'NR': t.Bool,
    'SI': None,
    'CB': t.uint8_t,
    'ND': t,  # "optional 2-Byte NI value"
    'DN': t.Bytes,  # "up to 20-Byte printable ASCII string"
    'IS': None,
    '1S': None,
    'AS': None,
    # Stuff I've guessed
    'CE': t.uint8_t,
}


class XBee:
    MODEM_STATUS = {
        0x00: 'Hardware reset',
        0x01: 'Watchdog timer reset',
        0x02: 'Joined network (routers and end devices)',
        0x03: 'Disassociated',
        0x06: 'Coordinator started',
        0x07: 'Network security key was updated',
        0x0D: 'Voltage supply limit exceeded (PRO S2B only)',
        0x11: 'Modem configuration changed while join in progress',
    }

    def __init__(self):
        self._uart = None
        self._seq = 1
        self._commands_by_id = {v[0]: k for k, v in COMMANDS.items()}
        self._awaiting = {}
        self._app = None

    async def connect(self, device, baudrate=115200):
        assert self._uart is None
        self._uart = await uart.connect(device, baudrate, self)

    def close(self):
        return self._uart.close()

    def _command(self, name, *args):
        LOGGER.debug("Command %s %s", name, args)
        data, needs_response = self._api_frame(name, *args)
        self._uart.send(data)
        future = None
        if needs_response:
            future = asyncio.Future()
            self._awaiting[self._seq] = (future, )
        self._seq = (self._seq % 255) + 1
        return future

    def _seq_command(self, name, *args):
        LOGGER.debug("Sequenced command: %s %s", name, args)
        return self._command(name, self._seq, *args)

    def _at_command(self, name, *args):
        LOGGER.debug("AT command: %s %s", name, args)
        data = t.serialize(args, (AT_COMMANDS[name], ))
        return self._command(
            'at',
            self._seq,
            name.encode('ascii'),
            data,
        )

    def _api_frame(self, name, *args):
        c = COMMANDS[name]
        return (bytes([c[0]]) + t.serialize(args, c[1])), c[2]

    def frame_received(self, data):
        command = self._commands_by_id[data[0]]
        LOGGER.debug("Frame received: %s", command)
        data, rest = t.deserialize(data[1:], COMMANDS[command][1])
        getattr(self, '_handle_%s' % (command, ))(data)

    def _handle_at_response(self, data):
        fut, = self._awaiting.pop(data[0])
        if data[2]:
            fut.set_exception(Exception(data[2]))
            return

        response_type = AT_COMMANDS[data[1].decode('ascii')]
        if response_type is None or len(data[3]) == 0:
            fut.set_result(None)
            return

        response, remains = response_type.deserialize(data[3])
        fut.set_result(response)

    def _handle_modem_status(self, data):
        LOGGER.debug("data = %s", data)
        if self._app:
            self._app.handle_modem_status(data[0])

    def _handle_explicit_rx_indicator(self, data):
        LOGGER.debug("_handle_explicit_rx: opts=%s", data[6])
        self._app.handle_rx(*data)

    def _handle_tx_status(self, data):
        LOGGER.debug("tx_status: %s", data)

    def set_application(self, app):
        self._app = app
