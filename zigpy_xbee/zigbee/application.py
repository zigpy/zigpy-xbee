import asyncio
import binascii
import logging

import zigpy.application
import zigpy.exceptions
import zigpy.device
import zigpy.quirks
import zigpy.types
import zigpy.util
from zigpy.zcl.clusters.general import Groups
from zigpy.zdo.types import LogicalType, NodeDescriptor

from zigpy_xbee.types import UNKNOWN_IEEE


# how long coordinator would hold message for an end device in 10ms units
CONF_CYCLIC_SLEEP_PERIOD = 0x0300
# end device poll timeout = 3 * SN * SP * 10ms
CONF_POLL_TIMEOUT = 0x029B
TIMEOUT_TX_STATUS = 120
TIMEOUT_REPLY = 5
TIMEOUT_REPLY_EXTENDED = 28

LOGGER = logging.getLogger(__name__)

XBEE_ENDPOINT_ID = 0xE6


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
            await self._api._at_command("AP", 2)
        except asyncio.TimeoutError:
            LOGGER.debug("No response to API frame. Configure API mode")
            if not await self._api.init_api_mode():
                LOGGER.error("Failed to configure XBee API mode.")
                return False

        await self._api._at_command("AO", 0x03)

        serial_high = await self._api._at_command("SH")
        serial_low = await self._api._at_command("SL")
        as_bytes = serial_high.to_bytes(4, "big") + serial_low.to_bytes(4, "big")
        self._ieee = zigpy.types.EUI64([zigpy.types.uint8_t(b) for b in as_bytes])
        LOGGER.debug("Read local IEEE address as %s", self._ieee)

        association_state = await self._get_association_state()
        self._nwk = await self._api._at_command("MY")
        enc_enabled = await self._api._at_command("EE")
        enc_options = await self._api._at_command("EO")
        zb_profile = await self._api._at_command("ZS")

        should_form = (
            enc_enabled != 1,
            enc_options != 2,
            zb_profile != 2,
            association_state != 0,
            self._nwk != 0,
        )
        if auto_form and any(should_form):
            await self.form_network()

        await self._api._at_command("NJ", 0)
        await self._api._at_command("SP", CONF_CYCLIC_SLEEP_PERIOD)
        await self._api._at_command("SN", CONF_POLL_TIMEOUT)
        id = await self._api._at_command("ID")
        LOGGER.debug("Extended PAN ID: 0x%016x", id)
        id = await self._api._at_command("OP")
        LOGGER.debug("Operating Extended PAN ID: 0x%016x", id)
        id = await self._api._at_command("OI")
        LOGGER.debug("PAN ID: 0x%04x", id)
        try:
            ce = await self._api._at_command("CE")
            LOGGER.debug("Coordinator %s", "enabled" if ce else "disabled")
        except RuntimeError as exc:
            LOGGER.debug("sending CE command: %s", exc)

        dev = zigpy.device.Device(self, self.ieee, self.nwk)
        dev.add_endpoint(XBEE_ENDPOINT_ID)
        self.listener_event("raw_device_initialized", dev)
        xbee_dev = XBeeCoordinator(self, self.ieee, self.nwk, dev)
        self.devices[dev.ieee] = xbee_dev

    async def force_remove(self, dev):
        """Forcibly remove device from NCP."""
        pass

    async def form_network(self, channel=15, pan_id=None, extended_pan_id=None):
        LOGGER.info("Forming network on channel %s", channel)
        scan_bitmask = 1 << (channel - 11)
        await self._api._queued_at("ZS", 2)
        await self._api._queued_at("SC", scan_bitmask)
        await self._api._queued_at("EE", 1)
        await self._api._queued_at("EO", 2)
        await self._api._queued_at("NK", 0)
        await self._api._queued_at("KY", b"ZigBeeAlliance09")
        await self._api._queued_at("NJ", 0)
        await self._api._queued_at("SP", CONF_CYCLIC_SLEEP_PERIOD)
        await self._api._queued_at("SN", CONF_POLL_TIMEOUT)
        try:
            await self._api._queued_at("CE", 1)
        except RuntimeError:
            pass
        await self._api._at_command("WR")

        await asyncio.wait_for(self._api.coordinator_started_event.wait(), timeout=10)
        association_state = await self._get_association_state()
        LOGGER.debug("Association state: %s", association_state)
        self._nwk = await self._api._at_command("MY")
        assert self._nwk == 0x0000

    async def _get_association_state(self):
        """Wait for Zigbee to start."""
        state = await self._api._at_command("AI")
        while state == 0xFF:
            LOGGER.debug("Waiting for radio startup...")
            await asyncio.sleep(0.2)
            state = await self._api._at_command("AI")
        return state

    @zigpy.util.retryable_request
    async def request(
        self,
        nwk,
        profile,
        cluster,
        src_ep,
        dst_ep,
        sequence,
        data,
        expect_reply=True,
        timeout=TIMEOUT_REPLY,
    ):
        LOGGER.debug("Zigbee request seq %s", sequence)
        assert sequence not in self._pending
        if expect_reply:
            reply_fut = asyncio.Future()
            self._pending[sequence] = reply_fut

        dev = self.get_device(nwk=nwk)
        if dev.node_desc.logical_type in (LogicalType.EndDevice, None):
            tx_opts = 0x60
            rx_timeout = TIMEOUT_REPLY_EXTENDED
        else:
            tx_opts = 0x20
            rx_timeout = timeout
        send_req = self._api.tx_explicit(
            dev.ieee, nwk, src_ep, dst_ep, cluster, profile, 0, tx_opts, data
        )

        try:
            v = await asyncio.wait_for(send_req, timeout=TIMEOUT_TX_STATUS)
        except (asyncio.TimeoutError, zigpy.exceptions.DeliveryError) as ex:
            LOGGER.debug(
                "[0x%04x:%s:0x%04x]: Error sending message: %s",
                nwk,
                dst_ep,
                cluster,
                ex,
            )
            self._pending.pop(sequence, None)
            raise zigpy.exceptions.DeliveryError(
                "[0x{:04x}:{}:0x{:04x}]: Delivery Error".format(nwk, dst_ep, cluster)
            )
        if expect_reply:
            try:
                return await asyncio.wait_for(reply_fut, rx_timeout)
            except asyncio.TimeoutError as ex:
                LOGGER.debug(
                    "[0x%04x:%s:0x%04x]: no reply: %s", nwk, dst_ep, cluster, ex
                )
                raise zigpy.exceptions.DeliveryError(
                    "[0x{:04x}:{}:{:04x}]: no reply".format(nwk, dst_ep, cluster)
                )
            finally:
                self._pending.pop(sequence, None)
        return v

    @zigpy.util.retryable_request
    def remote_at_command(
        self, nwk, cmd_name, *args, apply_changes=True, encryption=True
    ):
        LOGGER.debug("Remote AT%s command: %s", cmd_name, args)
        options = zigpy.types.uint8_t(0)
        if apply_changes:
            options |= 0x02
        if encryption:
            options |= 0x20
        dev = self.get_device(nwk=nwk)
        return self._api._remote_at_command(dev.ieee, nwk, options, cmd_name, *args)

    async def permit_ncp(self, time_s=60):
        assert 0 <= time_s <= 254
        await self._api._at_command("NJ", time_s)
        await self._api._at_command("AC")
        await self._api._at_command("CB", 2)

    def handle_modem_status(self, status):
        LOGGER.info("Modem status update: %s (%s)", status.name, status.value)

    def handle_rx(
        self, src_ieee, src_nwk, src_ep, dst_ep, cluster_id, profile_id, rxopts, data
    ):
        if src_nwk == 0:
            # I'm not sure why we've started seeing ZDO requests from ourself.
            # Ignore for now.
            LOGGER.info("handle_rx self addressed")

        ember_ieee = zigpy.types.EUI64(src_ieee)
        if dst_ep == 0 and cluster_id == 0x13:
            # ZDO Device announce request
            nwk, rest = zigpy.types.NWK.deserialize(data[1:])
            ieee, rest = zigpy.types.EUI64.deserialize(rest)
            LOGGER.info("New device joined: NWK 0x%04x, IEEE %s", nwk, ieee)
            if ember_ieee != ieee:
                LOGGER.warning(
                    "Announced IEEE %s is different from originator %s",
                    str(ieee),
                    str(ember_ieee),
                )
            if src_nwk != nwk:
                LOGGER.warning(
                    "Announced 0x%04x NWK is different from originator 0x%04x",
                    nwk,
                    src_nwk,
                )
            self.handle_join(nwk, ieee, 0)

        try:
            device = self.get_device(nwk=src_nwk)
        except KeyError:
            if ember_ieee != UNKNOWN_IEEE and ember_ieee in self.devices:
                self.handle_join(src_nwk, ember_ieee, 0)
                device = self.get_device(ieee=ember_ieee)
            else:
                LOGGER.debug(
                    "Received frame from unknown device: 0x%04x/%s",
                    src_nwk,
                    str(ember_ieee),
                )
                return

        if device.status == zigpy.device.Status.NEW and dst_ep != 0:
            # only allow ZDO responses while initializing device
            LOGGER.debug(
                "Received frame on uninitialized device %s (%s) for endpoint: %s",
                device.ieee,
                device.status,
                dst_ep,
            )
            return
        elif (
            device.status == zigpy.device.Status.ZDO_INIT
            and dst_ep != 0
            and cluster_id != 0
        ):
            # only allow access to basic cluster while initializing endpoints
            LOGGER.debug(
                "Received frame on uninitialized device %s endpoint %s for cluster: %s",
                device.ieee,
                dst_ep,
                cluster_id,
            )
            return

        try:
            tsn, command_id, is_reply, args = self.deserialize(
                device, src_ep, cluster_id, data
            )
        except ValueError as e:
            LOGGER.error(
                "Failed to parse message (%s) on cluster %s, because %s",
                binascii.hexlify(data),
                cluster_id,
                e,
            )
            return

        if is_reply:
            self._handle_reply(
                device, profile_id, cluster_id, src_ep, dst_ep, tsn, command_id, args
            )
        else:
            self.handle_message(
                device,
                False,
                profile_id,
                cluster_id,
                src_ep,
                dst_ep,
                tsn,
                command_id,
                args,
            )

    def _handle_reply(
        self, device, profile, cluster, src_ep, dst_ep, tsn, command_id, args
    ):
        try:
            reply_fut = self._pending[tsn]
            if reply_fut:
                self._pending.pop(tsn)
                reply_fut.set_result(args)
            return
        except KeyError:
            LOGGER.warning(
                "Unexpected response TSN=%s command=%s args=%s", tsn, command_id, args
            )
        except asyncio.futures.InvalidStateError as exc:
            LOGGER.debug(
                "Invalid state on future - probably duplicate response: %s", exc
            )
            # We've already handled, don't drop through to device handler
            return

        self.handle_message(
            device, True, profile, cluster, src_ep, dst_ep, tsn, command_id, args
        )

    async def broadcast(
        self,
        profile,
        cluster,
        src_ep,
        dst_ep,
        grpid,
        radius,
        sequence,
        data,
        broadcast_address=zigpy.types.BroadcastAddress.RX_ON_WHEN_IDLE,
    ):
        LOGGER.debug("Broadcast request seq %s", sequence)
        assert sequence not in self._pending
        broadcast_as_bytes = [
            zigpy.types.uint8_t(b) for b in broadcast_address.to_bytes(8, "big")
        ]
        request = self._api.tx_explicit(
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
        return await asyncio.wait_for(request, timeout=TIMEOUT_TX_STATUS)


class XBeeCoordinator(zigpy.quirks.CustomDevice):
    class XBeeGroup(zigpy.quirks.CustomCluster, Groups):
        cluster_id = 0x0006

    class XBeeGroupResponse(zigpy.quirks.CustomCluster, Groups):
        import zigpy.zcl.foundation as f

        cluster_id = 0x8006
        ep_attribute = "xbee_groups_response"

        client_commands = {**Groups.client_commands}
        client_commands[0x0004] = ("remove_all_response", (f.Status,), True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.node_desc = NodeDescriptor(
            0x01, 0x40, 0x8E, 0x101E, 0x52, 0x00FF, 0x2C00, 0x00FF, 0x00
        )

    replacement = {
        "manufacturer": "Digi",
        "model": "XBee",
        "endpoints": {
            XBEE_ENDPOINT_ID: {
                "device_type": 0x0050,
                "profile_id": 0xC105,
                "input_clusters": [XBeeGroup, XBeeGroupResponse],
                "output_clusters": [],
            }
        },
    }
