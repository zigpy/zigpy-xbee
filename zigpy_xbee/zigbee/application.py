from __future__ import annotations

import asyncio
import binascii
import logging
import time
from typing import Any

import zigpy.application
import zigpy.config
import zigpy.device
import zigpy.exceptions
import zigpy.quirks
import zigpy.types
import zigpy.util
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import Groups
import zigpy.zdo.types as zdo_t

import zigpy_xbee
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

    def __init__(self, config: dict[str, Any]):
        super().__init__(config=zigpy.config.ZIGPY_SCHEMA(config))
        self._api: zigpy_xbee.api.XBee | None = None

    async def disconnect(self):
        """Shutdown application."""
        if self._api:
            self._api.close()

    async def connect(self):
        self._api = await zigpy_xbee.api.XBee.new(self, self._config[CONF_DEVICE])
        try:
            # Ensure we have escaped commands
            await self._api._at_command("AP", 2)
        except asyncio.TimeoutError:
            LOGGER.debug("No response to API frame. Configure API mode")
            if not await self._api.init_api_mode():
                raise zigpy.exceptions.ControllerException(
                    "Failed to configure XBee API mode."
                )

    async def start_network(self):
        association_state = await asyncio.wait_for(
            self._get_association_state(), timeout=4
        )

        # Enable ZDO passthrough
        await self._api._at_command("AO", 0x03)

        enc_enabled = await self._api._at_command("EE")
        enc_options = await self._api._at_command("EO")
        zb_profile = await self._api._at_command("ZS")

        if (
            enc_enabled != 1
            or enc_options != 2
            or zb_profile != 2
            or association_state != 0
            or self.state.node_info.nwk != 0x0000
        ):
            raise zigpy.exceptions.NetworkNotFormed("Network is not formed")

        # Disable joins
        await self._api._at_command("NJ", 0)
        await self._api._at_command("SP", CONF_CYCLIC_SLEEP_PERIOD)
        await self._api._at_command("SN", CONF_POLL_TIMEOUT)

        dev = zigpy.device.Device(
            self, self.state.node_info.ieee, self.state.node_info.nwk
        )
        dev.status = zigpy.device.Status.ENDPOINTS_INIT
        dev.add_endpoint(XBEE_ENDPOINT_ID)

        xbee_dev = XBeeCoordinator(
            self, self.state.node_info.ieee, self.state.node_info.nwk, dev
        )
        self.listener_event("raw_device_initialized", xbee_dev)
        self.devices[dev.ieee] = xbee_dev

    async def load_network_info(self, *, load_devices=False):
        # Load node info
        node_info = self.state.node_info
        node_info.nwk = zigpy.types.NWK(await self._api._at_command("MY"))
        serial_high = await self._api._at_command("SH")
        serial_low = await self._api._at_command("SL")
        node_info.ieee = zigpy.types.EUI64(
            (serial_high.to_bytes(4, "big") + serial_low.to_bytes(4, "big"))[::-1]
        )

        try:
            if await self._api._at_command("CE") == 0x01:
                node_info.logical_type = zdo_t.LogicalType.Coordinator
            else:
                node_info.logical_type = zdo_t.LogicalType.EndDevice
        except RuntimeError:
            LOGGER.warning("CE command failed, assuming node is coordinator")
            node_info.logical_type = zdo_t.LogicalType.Coordinator

        # Load network info
        pan_id = await self._api._at_command("OI")
        extended_pan_id = await self._api._at_command("ID")

        network_info = self.state.network_info
        network_info.source = f"zigpy-xbee@{zigpy_xbee.__version__}"
        network_info.pan_id = zigpy.types.PanId(pan_id)
        network_info.extended_pan_id = zigpy.types.ExtendedPanId(
            zigpy.types.uint64_t(extended_pan_id).serialize()
        )
        network_info.channel = await self._api._at_command("CH")

    async def write_network_info(self, *, network_info, node_info):
        scan_bitmask = 1 << (network_info.channel - 11)

        await self._api._queued_at("ZS", 2)
        await self._api._queued_at("SC", scan_bitmask)
        await self._api._queued_at("EE", 1)
        await self._api._queued_at("EO", 2)

        await self._api._queued_at("NK", network_info.network_key.key.serialize())
        await self._api._queued_at("KY", network_info.tc_link_key.key.serialize())

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

    async def force_remove(self, dev):
        """Forcibly remove device from NCP."""
        pass

    async def add_endpoint(self, descriptor):
        """Register a new endpoint on the device."""
        # This is not provided by the XBee API
        pass

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
        non_member_radius=3,
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
            return v, f"Error sending tsn #{sequence}: {v.name}"
        return v, f"Successfully sent tsn #{sequence}: {v.name}"

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
            return v, f"Error sending tsn #{sequence}: {v.name}"
        return v, f"Succesfuly sent tsn #{sequence}: {v.name}"

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

    async def permit_with_key(self, node, code, time_s=60):
        raise NotImplementedError("XBee does not support install codes")

    def handle_modem_status(self, status):
        LOGGER.info("Modem status update: %s (%s)", status.name, status.value)

    def handle_rx(
        self, src_ieee, src_nwk, src_ep, dst_ep, cluster_id, profile_id, rxopts, data
    ):
        if src_nwk == 0:
            LOGGER.info("handle_rx self addressed")

        ember_ieee = zigpy.types.EUI64(src_ieee)
        if dst_ep == 0 and cluster_id == zdo_t.ZDOCmd.Device_annce:
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
            self._device.last_seen = time.time()
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
            return v, f"Error sending broadcast tsn #{sequence}: {v.name}"
        return v, f"Succesfuly sent broadcast tsn #{sequence}: {v.name}"


class XBeeCoordinator(zigpy.quirks.CustomDevice):
    class XBeeGroup(zigpy.quirks.CustomCluster, Groups):
        cluster_id = 0x0006

    class XBeeGroupResponse(zigpy.quirks.CustomCluster, Groups):
        cluster_id = 0x8006
        ep_attribute = "xbee_groups_response"

        client_commands = {
            **Groups.client_commands,
            0x04: foundation.ZCLCommandDef(
                "remove_all_response", {"status": foundation.Status}, is_reply=True
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.node_desc = zdo_t.NodeDescriptor(
            logical_type=zdo_t.LogicalType.Coordinator,
            complex_descriptor_available=0,
            user_descriptor_available=0,
            reserved=0,
            aps_flags=0,
            frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
            mac_capability_flags=(
                zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress
                | zdo_t.NodeDescriptor.MACCapabilityFlags.RxOnWhenIdle
                | zdo_t.NodeDescriptor.MACCapabilityFlags.MainsPowered
                | zdo_t.NodeDescriptor.MACCapabilityFlags.FullFunctionDevice
            ),
            manufacturer_code=4126,
            maximum_buffer_size=82,
            maximum_incoming_transfer_size=255,
            server_mask=11264,
            maximum_outgoing_transfer_size=255,
            descriptor_capability_field=zdo_t.NodeDescriptor.DescriptorCapability.NONE,
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
