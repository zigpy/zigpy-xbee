import asyncio
import logging

import zigpy.application
import zigpy.types
import zigpy.util
import zigpy.zcl
import zigpy.zdo


LOGGER = logging.getLogger(__name__)


class ControllerApplication(zigpy.application.ControllerApplication):
    def __init__(self, api, database_file=None):
        super().__init__(database_file=database_file)
        self._api = api
        api.set_application(self)

        self._pending = {}
        self._devices_by_nwk = {}

        self._nwk = 0

    @asyncio.coroutine
    def initialize(self):
        """Perform basic radio initialization"""
        yield from self._api._at_command('AP', 2)  # Ensure we have escaped commands
        yield from self._api._at_command('AO', 0x03)

        serial_high = yield from self._api._at_command('SH')
        serial_low = yield from self._api._at_command('SL')
        as_bytes = serial_high.to_bytes(4, 'big') + serial_low.to_bytes(4, 'big')
        self._ieee = zigpy.types.EUI64([zigpy.types.uint8_t(b) for b in as_bytes])

    @asyncio.coroutine
    def startup(self, auto_form=False):
        """Perform a complete application startup"""
        yield from self.initialize()

    @asyncio.coroutine
    def form_network(self, channel=15, pan_id=None, extended_pan_id=None):
        yield from self._api._at_command('AI')

        scan_bitmask = 1 << (channel - 11)
        yield from self._api._at_command('ZS', 2)
        yield from self._api._at_command('SC', scan_bitmask)
        yield from self._api._at_command('EE', 1)
        yield from self._api._at_command('EO', 2)
        yield from self._api._at_command('NK', 0)
        yield from self._api._at_command('KY', b'ZigBeeAlliance09')
        yield from self._api._at_command('WR')
        yield from self._api._at_command('AC')
        yield from self._api._at_command('CE', 1)

        # When the coordinator has successfully started a network, it
        #  Allows other devices to join the network for a time (see NJ command)
        #  Sets AI=0
        #  Starts blinking the Associate LED
        #  Sends an API modem status frame (“coordinator started”) out the UART (API firmware only)

    @zigpy.util.retryable_request
    @asyncio.coroutine
    def request(self, nwk, profile, cluster, src_ep, dst_ep, sequence, data, expect_reply=True, timeout=10):
        LOGGER.debug("Zigbee request seq %s", sequence)
        assert sequence not in self._pending
        reply_fut = asyncio.Future()
        self._pending[sequence] = reply_fut
        self._api._seq_command(
            'tx_explicit',
            self._devices_by_nwk[nwk],
            nwk,
            src_ep,
            dst_ep,
            cluster,
            profile,
            0,
            0x20,
            data,
        )
        v = yield from asyncio.wait_for(reply_fut, timeout)
        return v

    @asyncio.coroutine
    def permit(self, time_s=60):
        assert 0 <= time_s <= 254
        yield from self._api._at_command('NJ', time_s)
        yield from self._api._at_command('AC')
        yield from self._api._at_command('CB', 2)

    def handle_modem_status(self, status):
        LOGGER.info("Modem status update: %s", status)

    def handle_rx(self, src_ieee, src_nwk, src_ep, dst_ep, cluster_id, profile_id, rxopts, data):
        self._devices_by_nwk[src_nwk] = src_ieee

        if dst_ep == 0:
            deserialize = zigpy.zdo.deserialize
        else:
            deserialize = zigpy.zcl.deserialize

        tsn, command_id, is_reply, args = deserialize(cluster_id, data)

        if is_reply:
            self._handle_reply(src_nwk, profile_id, cluster_id, src_ep, dst_ep, tsn, command_id, args)
        else:
            ember_ieee = zigpy.types.EUI64(src_ieee)
            if src_ieee not in self.devices:
                self.handle_join(src_nwk, ember_ieee, 0)
            else:
                self.devices[ember_ieee].nwk = src_nwk
            self.handle_message(False, src_nwk, profile_id, cluster_id, src_ep, dst_ep, tsn, command_id, args)

    def _handle_reply(self, sender, profile, cluster, src_ep, dst_ep, tsn, command_id, args):
        try:
            reply_fut = self._pending[tsn]
            if reply_fut:
                self._pending.pop(tsn)
                reply_fut.set_result(args)
            return
        except KeyError:
            LOGGER.warning("Unexpected response TSN=%s command=%s args=%s", tsn, command_id, args)
        except asyncio.futures.InvalidStateError as exc:
            LOGGER.debug("Invalid state on future - probably duplicate response: %s", exc)
            # We've already handled, don't drop through to device handler
            return

        self.handle_message(True, sender, profile, cluster, src_ep, dst_ep, tsn, command_id, args)
