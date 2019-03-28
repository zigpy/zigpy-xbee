import asyncio
import binascii
import logging

import zigpy.application
import zigpy.types
import zigpy.util


# how long coordinator would hold message for an end device in 10ms units
CONF_CYCLIC_SLEEP_PERIOD = 0x0300
# end device poll timeout = 3 * SN * SP * 10ms
CONF_POLL_TIMEOUT = 0x029b

LOGGER = logging.getLogger(__name__)


class ControllerApplication(zigpy.application.ControllerApplication):
    def __init__(self, api, database_file=None):
        super().__init__(database_file=database_file)
        self._api = api
        api.set_application(self)

        self._pending = {}
        self._nwk = 0

    async def shutdown(self):
        """Shutdown application."""
        self._api.close()

    async def startup(self, auto_form=False):
        """Perform a complete application startup"""
        try:
            # Ensure we have escaped commands
            await self._api._at_command('AP', 2)
        except asyncio.TimeoutError:
            LOGGER.debug("No response to API frame. Configure API mode")
            if not await self._api.init_api_mode():
                LOGGER.error("Failed to configure XBee API mode.")
                return False

        await self._api._at_command('AO', 0x03)

        serial_high = await self._api._at_command('SH')
        serial_low = await self._api._at_command('SL')
        as_bytes = serial_high.to_bytes(4, 'big') + serial_low.to_bytes(4, 'big')
        self._ieee = zigpy.types.EUI64([zigpy.types.uint8_t(b) for b in as_bytes])
        LOGGER.debug("Read local IEEE address as %s", self._ieee)

        association_state = await self._get_association_state()
        self._nwk = await self._api._at_command('MY')
        enc_enabled = await self._api._at_command('EE')
        enc_options = await self._api._at_command('EO')
        zb_profile = await self._api._at_command('ZS')

        should_form = (enc_enabled != 1, enc_options != 2, zb_profile != 2,
                       association_state != 0, self._nwk != 0)
        if auto_form and any(should_form):
            await self.form_network()

        await self._api._at_command('NJ', 0)
        await self._api._at_command('SP', CONF_CYCLIC_SLEEP_PERIOD)
        await self._api._at_command('SN', CONF_POLL_TIMEOUT)
        id = await self._api._at_command('ID')
        LOGGER.debug("Extended PAN ID: 0x%016x", id)
        id = await self._api._at_command('OP')
        LOGGER.debug("Operating Extended PAN ID: 0x%016x", id)
        id = await self._api._at_command('OI')
        LOGGER.debug("PAN ID: 0x%04x", id)
        try:
            ce = await self._api._at_command('CE')
            LOGGER.debug("Coordinator %s", 'enabled' if ce else 'disabled')
        except RuntimeError as exc:
            LOGGER.debug("sending CE command: %s", exc)

    async def force_remove(self, dev):
        """Forcibly remove device from NCP."""
        pass

    async def form_network(self, channel=15, pan_id=None, extended_pan_id=None):
        LOGGER.info("Forming network on channel %s", channel)
        scan_bitmask = 1 << (channel - 11)
        await self._api._queued_at('ZS', 2)
        await self._api._queued_at('SC', scan_bitmask)
        await self._api._queued_at('EE', 1)
        await self._api._queued_at('EO', 2)
        await self._api._queued_at('NK', 0)
        await self._api._queued_at('KY', b'ZigBeeAlliance09')
        await self._api._queued_at('NJ', 0)
        await self._api._queued_at('SP', CONF_CYCLIC_SLEEP_PERIOD)
        await self._api._queued_at('SN', CONF_POLL_TIMEOUT)
        try:
            await self._api._queued_at('CE', 1)
        except RuntimeError:
            pass
        await self._api._at_command('WR')

        await asyncio.wait_for(
            self._api.coordinator_started_event.wait(), timeout=10)
        association_state = await self._get_association_state()
        LOGGER.debug("Association state: %s", association_state)
        self._nwk = await self._api._at_command('MY')
        assert self._nwk == 0x0000

    async def _get_association_state(self):
        """Wait for Zigbee to start."""
        state = await self._api._at_command('AI')
        while state == 0xFF:
            LOGGER.debug("Waiting for radio startup...")
            await asyncio.sleep(0.2)
            state = await self._api._at_command('AI')
        return state

    @zigpy.util.retryable_request
    async def request(self, nwk, profile, cluster, src_ep, dst_ep, sequence, data, expect_reply=True, timeout=10):
        LOGGER.debug("Zigbee request seq %s", sequence)
        assert sequence not in self._pending
        if expect_reply:
            reply_fut = asyncio.Future()
            self._pending[sequence] = reply_fut

        dev = self.get_device(nwk=nwk)
        self._api._seq_command(
            'tx_explicit',
            dev.ieee,
            nwk,
            src_ep,
            dst_ep,
            cluster,
            profile,
            0,
            0x20,
            data,
        )
        if not expect_reply:
            return

        try:
            return await asyncio.wait_for(reply_fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(sequence, None)
            raise

    async def permit_ncp(self, time_s=60):
        assert 0 <= time_s <= 254
        await self._api._at_command('NJ', time_s)
        await self._api._at_command('AC')
        await self._api._at_command('CB', 2)

    def handle_modem_status(self, status):
        LOGGER.info("Modem status update: %s (%s)", status.name, status.value)

    def handle_rx(self, src_ieee, src_nwk, src_ep, dst_ep, cluster_id, profile_id, rxopts, data):
        if src_nwk == 0:
            # I'm not sure why we've started seeing ZDO requests from ourself.
            # Ignore for now.
            return

        ember_ieee = zigpy.types.EUI64(src_ieee)
        if dst_ep == 0 and cluster_id == 0x13:
            # ZDO Device announce request
            nwk, data = zigpy.types.uint16_t.deserialize(data[1:])
            ieee, data = zigpy.types.EUI64.deserialize(data)
            LOGGER.info("New device joined: NWK 0x%04x, IEEE %s", nwk, ieee)
            if ember_ieee != ieee:
                LOGGER.warning(
                    "Announced IEEE %s is different from originator %s",
                    str(ieee), str(ember_ieee))
            if src_nwk != nwk:
                LOGGER.warning(
                    "Announced 0x%04x NWK is different from originator 0x%04x",
                    nwk, src_nwk
                )
            self.handle_join(nwk, ieee, 0)

        try:
            if ember_ieee == zigpy.types.EUI64(b'\xff\xff\xff\xff\xff\xff\xff\xff'):
                LOGGER.debug("Device reports a generic ieee, looking up by nwk")
                device = self.get_device(nwk=src_nwk)
            else:
                device = self.get_device(ieee=ember_ieee)
        except KeyError:
            LOGGER.debug("Received frame from unknown device: 0x%04x/%s",
                         src_nwk, str(ember_ieee))
            return

        if device.status == zigpy.device.Status.NEW and dst_ep != 0:
            # only allow ZDO responses while initializing device
            LOGGER.debug("Received frame on uninitialized device %s (%s) for endpoint: %s", device.ieee, device.status, dst_ep)
            return
        elif device.status == zigpy.device.Status.ZDO_INIT and dst_ep != 0 and cluster_id != 0:
            # only allow access to basic cluster while initializing endpoints
            LOGGER.debug("Received frame on uninitialized device %s endpoint %s for cluster: %s", device.ieee, dst_ep, cluster_id)
            return

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

    async def broadcast(self, profile, cluster, src_ep, dst_ep, grpid, radius,
                        sequence, data,
                        broadcast_address=zigpy.types.BroadcastAddress.RX_ON_WHEN_IDLE):
        LOGGER.debug("Broadcast request seq %s", sequence)
        assert sequence not in self._pending
        broadcast_as_bytes = [
            zigpy.types.uint8_t(b) for b in broadcast_address.to_bytes(8, 'big')
        ]
        self._api._seq_command(
            'tx_explicit',
            zigpy.types.EUI64(broadcast_as_bytes),
            broadcast_address,
            src_ep,
            dst_ep,
            cluster,
            profile,
            radius,
            0x20,
            data,
        )
