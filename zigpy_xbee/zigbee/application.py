import asyncio
import binascii
import logging

import zigpy.application
import zigpy.types
import zigpy.util


LOGGER = logging.getLogger(__name__)


class ControllerApplication(zigpy.application.ControllerApplication):
    def __init__(self, api, database_file=None):
        super().__init__(database_file=database_file)
        self._api = api
        api.set_application(self)

        self._pending = {}
        self._devices_by_nwk = {}

        self._nwk = 0

    async def startup(self, auto_form=False):
        """Perform a complete application startup"""
        await self._api._at_command('AP', 2)  # Ensure we have escaped commands
        await self._api._at_command('AO', 0x03)

        serial_high = await self._api._at_command('SH')
        serial_low = await self._api._at_command('SL')
        as_bytes = serial_high.to_bytes(4, 'big') + serial_low.to_bytes(4, 'big')
        self._ieee = zigpy.types.EUI64([zigpy.types.uint8_t(b) for b in as_bytes])
        LOGGER.debug("Read local IEEE address as %s", self._ieee)

        association_state = await self._api._at_command('AI')
        while association_state == 0xFF:
            LOGGER.debug("Waiting for radio startup...")
            await asyncio.sleep(0.2)
            association_state = await self._api._at_command('AI')

        self._nwk = await self._api._at_command('MY')

        if auto_form and not (association_state == 0 and self._nwk == 0):
            await self.form_network()

    async def form_network(self, channel=15, pan_id=None, extended_pan_id=None):
        LOGGER.info("Forming network on channel %s", channel)
        await self._api._at_command('AI')

        scan_bitmask = 1 << (channel - 11)
        await self._api._at_command('ZS', 2)
        await self._api._at_command('SC', scan_bitmask)
        await self._api._at_command('EE', 1)
        await self._api._at_command('EO', 2)
        await self._api._at_command('NK', 0)
        await self._api._at_command('KY', b'ZigBeeAlliance09')
        await self._api._at_command('WR')
        await self._api._at_command('AC')
        await self._api._at_command('CE', 1)

        self._nwk = await self._api._at_command('MY')

    @zigpy.util.retryable_request
    async def request(self, nwk, profile, cluster, src_ep, dst_ep, sequence, data, expect_reply=True, timeout=10):
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
        v = await asyncio.wait_for(reply_fut, timeout)
        return v

    async def permit(self, time_s=60):
        assert 0 <= time_s <= 254
        await self._api._at_command('NJ', time_s)
        await self._api._at_command('AC')
        await self._api._at_command('CB', 2)

    def handle_modem_status(self, status):
        LOGGER.info("Modem status update: %s (%s)", self._api.MODEM_STATUS.get(status, 'Unknown'), status)

    def handle_rx(self, src_ieee, src_nwk, src_ep, dst_ep, cluster_id, profile_id, rxopts, data):
        if src_nwk == 0:
            # I'm not sure why we've started seeing ZDO requests from ourself.
            # Ignore for now.
            return

        ember_ieee = zigpy.types.EUI64(src_ieee)
        if ember_ieee not in self.devices:
            self.handle_join(src_nwk, ember_ieee, 0)  # TODO: Parent nwk
        self._devices_by_nwk[src_nwk] = src_ieee
        device = self.get_device(ember_ieee)

        try:
            tsn, command_id, is_reply, args = self.deserialize(device, src_ep, cluster_id, data)
        except ValueError as e:
            LOGGER.error("Failed to parse message (%s) on cluster %d, because %s", binascii.hexlify(data), cluster_id, e)
            return

        if is_reply:
            self._handle_reply(device, profile_id, cluster_id, src_ep, dst_ep, tsn, command_id, args)
        else:
            self.handle_message(device, False, profile_id, cluster_id, src_ep, dst_ep, tsn, command_id, args)

    def _handle_reply(self, device, profile, cluster, src_ep, dst_ep, tsn, command_id, args):
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

        self.handle_message(device, True, profile, cluster, src_ep, dst_ep, tsn, command_id, args)
