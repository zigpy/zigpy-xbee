import asyncio
import binascii
import logging
import time
from typing import Any, Dict, Optional

import zigpy.application
import zigpy.config
import zigpy.device
import zigpy.exceptions
import zigpy.quirks
import zigpy.types
import zigpy.util
from zigpy.zcl.clusters.general import Groups
from zigpy.zdo.types import NodeDescriptor, ZDOCmd

import zigpy_xbee.api
from zigpy_xbee.config import CONF_DEVICE, CONFIG_SCHEMA, SCHEMA_DEVICE
from zigpy_xbee.types import EUI64, UNKNOWN_IEEE, UNKNOWN_NWK, TXStatus

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
    SCHEMA = CONFIG_SCHEMA
    SCHEMA_DEVICE = SCHEMA_DEVICE

    probe = zigpy_xbee.api.XBee.probe

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config=zigpy.config.ZIGPY_SCHEMA(config))
        self._api: Optional[zigpy_xbee.api.XBee] = None
        self._nwk = 0

    async def shutdown(self):
        """Shutdown application."""
        if self._api:
            self._api.close()

    async def startup(self, auto_form=False):
        """Perform a complete application startup"""
        self._api = await zigpy_xbee.api.XBee.new(self, self._config[CONF_DEVICE])
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
        ieee = EUI64.deserialize(
            serial_high.to_bytes(4, "big") + serial_low.to_bytes(4, "big")
        )[0]
        self._ieee = zigpy.types.EUI64(ieee)
        LOGGER.debug("Read local IEEE address as %s", self._ieee)

        try:
            association_state = await asyncio.wait_for(
                self._get_association_state(), timeout=4
            )
        except asyncio.TimeoutError:
            association_state = 0xFF
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
        dev.status = zigpy.device.Status.ENDPOINTS_INIT
        dev.add_endpoint(XBEE_ENDPOINT_ID)
        xbee_dev = XBeeCoordinator(self, self.ieee, self.nwk, dev)
        self.listener_event("raw_device_initialized", xbee_dev)
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
        association_state = await asyncio.wait_for(
            self._get_association_state(), timeout=10
        )
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

    async def mrequest(
        self,
        group_id,
        profile,
        cluster,
        src_ep,
        sequence,
        data,
        *,
        hops=0,
        non_member_radius=3
    ):
        """Submit and send data out as a multicast transmission.
        :param group_id: destination multicast address
        :param profile: Zigbee Profile ID to use for outgoing message
        :param cluster: cluster id where the message is being sent
        :param src_ep: source endpoint id
        :param sequence: transaction sequence number of the message
        :param data: Zigbee message payload
        :param hops: the message will be delivered to all nodes within this number of
                     hops of the sender. A value of zero is converted to MAX_HOPS
        :param non_member_radius: the number of hops that the message will be forwarded
                                  by devices that are not members of the group. A value
                                  of 7 or greater is treated as infinite
        :returns: return a tuple of a status and an error_message. Original requestor
                  has more context to provide a more meaningful error message
        """
        LOGGER.debug("Zigbee request tsn #%s: %s", sequence, binascii.hexlify(data))

        send_req = self._api.tx_explicit(
            UNKNOWN_IEEE, group_id, src_ep, src_ep, cluster, profile, hops, 0x08, data
        )

        try:
            v = await asyncio.wait_for(send_req, timeout=TIMEOUT_TX_STATUS)
        except asyncio.TimeoutError:
            return TXStatus.NETWORK_ACK_FAILURE, "Timeout waiting for ACK"

        if v != TXStatus.SUCCESS:
            return v, "Error sending tsn #%s: %s".format(sequence, v.name)
        return v, "Successfully sent tsn #%s: %s".format(sequence, v.name)

    async def request(
        self,
        device,
        profile,
        cluster,
        src_ep,
        dst_ep,
        sequence,
        data,
        expect_reply=True,
        use_ieee=False,
    ):
        """Submit and send data out as an unicast transmission.

        :param device: destination device
        :param profile: Zigbee Profile ID to use for outgoing message
        :param cluster: cluster id where the message is being sent
        :param src_ep: source endpoint id
        :param dst_ep: destination endpoint id
        :param sequence: transaction sequence number of the message
        :param data: Zigbee message payload
        :param expect_reply: True if this is essentially a request
        :param use_ieee: use EUI64 for destination addressing
        :returns: return a tuple of a status and an error_message. Original requestor
                  has more context to provide a more meaningful error message
        """
        LOGGER.debug("Zigbee request tsn #%s: %s", sequence, binascii.hexlify(data))

        tx_opts = 0x00
        if expect_reply and (
            device.node_desc is None or device.node_desc.is_end_device
        ):
            tx_opts |= 0x40
        send_req = self._api.tx_explicit(
            device.ieee,
            UNKNOWN_NWK if use_ieee else device.nwk,
            src_ep,
            dst_ep,
            cluster,
            profile,
            0,
            tx_opts,
            data,
        )

        try:
            v = await asyncio.wait_for(send_req, timeout=TIMEOUT_TX_STATUS)
        except asyncio.TimeoutError:
            return TXStatus.NETWORK_ACK_FAILURE, "Timeout waiting for ACK"

        if v != TXStatus.SUCCESS:
            return v, "Error sending tsn #%s: %s".format(sequence, v.name)
        return v, "Succesfuly sent tsn #%s: %s".format(sequence, v.name)

    @zigpy.util.retryable_request
    def remote_at_command(
        self, nwk, cmd_name, *args, apply_changes=True, encryption=True
    ):
        LOGGER.debug("Remote AT%s command: %s", cmd_name, args)
        options = zigpy.types.uint8_t(0)
        if apply_changes:
            options |= 0x02
        if encryption:
            options |= 0x10
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
            LOGGER.info("handle_rx self addressed")

        ember_ieee = zigpy.types.EUI64(src_ieee)
        if dst_ep == 0 and cluster_id == ZDOCmd.Device_annce:
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
            self.devices[self.ieee].last_seen = time.time()
        except KeyError:
            pass
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

        self.handle_message(device, profile_id, cluster_id, src_ep, dst_ep, data)

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
        """Submit and send data out as an broadcast transmission.

        :param profile: Zigbee Profile ID to use for outgoing message
        :param cluster: cluster id where the message is being sent
        :param src_ep: source endpoint id
        :param dst_ep: destination endpoint id
        :param grpid: group id to address the broadcast to
        :param radius: max radius of the broadcast
        :param sequence: transaction sequence number of the message
        :param data: zigbee message payload
        :param broadcast_address: broadcast address.
        :returns: return a tuple of a status and an error_message. Original requestor
                  has more context to provide a more meaningful error message
        """

        LOGGER.debug("Broadcast request seq %s", sequence)
        broadcast_as_bytes = [
            zigpy.types.uint8_t(b) for b in broadcast_address.to_bytes(8, "little")
        ]
        request = self._api.tx_explicit(
            EUI64(broadcast_as_bytes),
            broadcast_address,
            src_ep,
            dst_ep,
            cluster,
            profile,
            radius,
            0x00,
            data,
        )
        try:
            v = await asyncio.wait_for(request, timeout=TIMEOUT_TX_STATUS)
        except asyncio.TimeoutError:
            return TXStatus.NETWORK_ACK_FAILURE, "Timeout waiting for ACK"

        if v != TXStatus.SUCCESS:
            return v, "Error sending broadcast tsn #%s: %s".format(sequence, v.name)
        return v, "Succesfuly sent broadcast tsn #%s: %s".format(sequence, v.name)


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
            0x00, 0x40, 0x8E, 0x101E, 0x52, 0x00FF, 0x2C00, 0x00FF, 0x00
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
