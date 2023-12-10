"""ControllerApplication for XBee adapters."""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
from typing import Any

import zigpy.application
import zigpy.config
from zigpy.config import CONF_DEVICE
import zigpy.device
import zigpy.exceptions
import zigpy.quirks
import zigpy.state
import zigpy.types
import zigpy.util
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import Groups
import zigpy.zdo.types as zdo_t

import zigpy_xbee
import zigpy_xbee.api
import zigpy_xbee.config
from zigpy_xbee.exceptions import InvalidCommand
from zigpy_xbee.types import EUI64, UNKNOWN_IEEE, UNKNOWN_NWK, TXOptions, TXStatus

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
    """Implementation of Zigpy ControllerApplication for XBee devices."""

    CONFIG_SCHEMA = zigpy_xbee.config.CONFIG_SCHEMA

    def __init__(self, config: dict[str, Any]):
        """Initialize instance."""
        super().__init__(config=zigpy.config.ZIGPY_SCHEMA(config))
        self._api: zigpy_xbee.api.XBee | None = None
        self.topology.add_listener(self)

    async def disconnect(self):
        """Shutdown application."""
        if self._api:
            self._api.close()
            self._api = None

    async def connect(self):
        """Connect to the device."""
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
        """Configure the module to work with Zigpy."""
        association_state = await asyncio.wait_for(
            self._get_association_state(), timeout=4
        )

        # Enable ZDO passthrough
        await self._api._at_command("AO", 0x03)

        if self.state.node_info == zigpy.state.NodeInfo():
            await self.load_network_info()

        enc_enabled = await self._api._at_command("EE")
        enc_options = await self._api._at_command("EO")
        zb_profile = await self._api._at_command("ZS")

        if (
            enc_enabled != 1
            or enc_options & 0b0010 != 0b0010
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

        await self.register_endpoints()

    async def load_network_info(self, *, load_devices=False):
        """Load supported parameters of network_info and node_info from the device."""
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
        except InvalidCommand:
            LOGGER.warning("CE command failed, assuming node is coordinator")
            node_info.logical_type = zdo_t.LogicalType.Coordinator

        # TODO: Feature detect the XBee's exact model
        node_info.model = "XBee"
        node_info.manufacturer = "Digi"

        version = await self._api._at_command("VR")
        node_info.version = f"{int(version):#06x}"

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

    async def reset_network_info(self) -> None:
        """Reset Zigbee network."""
        await self._api._at_command("NR", 0)

    async def write_network_info(self, *, network_info, node_info):
        """Write supported network_info and node_info parameters to the device."""
        epid, _ = zigpy.types.uint64_t.deserialize(
            network_info.extended_pan_id.serialize()
        )
        await self._api._queued_at("ID", epid)

        await self._api._queued_at("ZS", 2)
        scan_bitmask = 1 << (network_info.channel - 11)
        await self._api._queued_at("SC", scan_bitmask)
        await self._api._queued_at("EE", 1)
        await self._api._queued_at("EO", 0b0010)
        await self._api._queued_at("NK", network_info.network_key.key.serialize())
        await self._api._queued_at("KY", network_info.tc_link_key.key.serialize())
        await self._api._queued_at("NJ", 0)
        await self._api._queued_at("SP", CONF_CYCLIC_SLEEP_PERIOD)
        await self._api._queued_at("SN", CONF_POLL_TIMEOUT)

        try:
            await self._api._queued_at("CE", 1)
        except InvalidCommand:
            pass

        await self._api._at_command("WR")

        await asyncio.wait_for(self._api.coordinator_started_event.wait(), timeout=10)
        association_state = await asyncio.wait_for(
            self._get_association_state(), timeout=10
        )
        LOGGER.debug("Association state: %s", association_state)

    async def _move_network_to_channel(
        self, new_channel: int, new_nwk_update_id: int
    ) -> None:
        """Move the coordinator to a new channel."""
        scan_bitmask = 1 << (new_channel - 11)
        await self._api._queued_at("SC", scan_bitmask)

    async def energy_scan(
        self, channels: zigpy.types.Channels, duration_exp: int, count: int
    ) -> dict[int, float]:
        """Run an energy detection scan and returns the per-channel scan results."""
        all_results = {}

        for _ in range(count):
            try:
                results = await self._api._at_command("ED", bytes([duration_exp]))
            except InvalidCommand:
                LOGGER.warning("Coordinator does not support energy scanning")
                return {c: 0 for c in channels}

            results = {
                channel: -int(rssi) for channel, rssi in zip(range(11, 27), results)
            }

            for channel, rssi in results.items():
                all_results.setdefault(channel, []).append(rssi)

        def logistic(x: float, *, L: float = 1, x_0: float = 0, k: float = 1) -> float:
            """Logistic function."""
            return L / (1 + math.exp(-k * (x - x_0)))

        def map_rssi_to_energy(rssi: int) -> float:
            """Remaps RSSI (in dBm) to Energy (0-255)."""
            RSSI_MAX = -5
            RSSI_MIN = -92
            return logistic(
                x=rssi,
                L=255,
                x_0=RSSI_MIN + 0.45 * (RSSI_MAX - RSSI_MIN),
                k=0.13,
            )

        energy = {
            channel: map_rssi_to_energy(statistics.mean(all_rssi))
            for channel, all_rssi in all_results.items()
        }

        return {channel: energy.get(channel, 0) for channel in channels}

    async def force_remove(self, dev):
        """Forcibly remove device from NCP."""

    async def add_endpoint(self, descriptor: zdo_t.SimpleDescriptor) -> None:
        """Register a new endpoint on the device."""
        self._device.replacement["endpoints"][descriptor.endpoint] = {
            "device_type": descriptor.device_type,
            "profile_id": descriptor.profile,
            "input_clusters": descriptor.input_clusters,
            "output_clusters": descriptor.output_clusters,
        }
        self._device.add_endpoint(descriptor.endpoint)

    async def _get_association_state(self):
        """Wait for Zigbee to start."""
        state = await self._api._at_command("AI")
        while state == 0xFF:
            LOGGER.debug("Waiting for radio startup...")
            await asyncio.sleep(0.2)
            state = await self._api._at_command("AI")
        return state

    async def send_packet(self, packet: zigpy.types.ZigbeePacket) -> None:
        """Send ZigbeePacket via the device."""
        LOGGER.debug("Sending packet %r", packet)

        try:
            device = self.get_device_with_address(packet.dst)
        except (KeyError, ValueError):
            device = None

        tx_opts = TXOptions.NONE

        if packet.extended_timeout:
            tx_opts |= TXOptions.Use_Extended_TX_Timeout

        if packet.dst.addr_mode == zigpy.types.AddrMode.Group:
            tx_opts |= 0x08  # where did this come from?

        long_addr = UNKNOWN_IEEE
        short_addr = UNKNOWN_NWK

        if packet.dst.addr_mode == zigpy.types.AddrMode.Broadcast:
            long_addr = EUI64(
                [
                    zigpy.types.uint8_t(b)
                    for b in packet.dst.address.to_bytes(8, "little")
                ]
            )
            short_addr = packet.dst.address
        elif packet.dst.addr_mode == zigpy.types.AddrMode.Group:
            short_addr = packet.dst.address
        elif packet.dst.addr_mode == zigpy.types.AddrMode.IEEE:
            long_addr = EUI64(packet.dst.address)
        elif device is not None:
            long_addr = EUI64(device.ieee)
            short_addr = device.nwk
        else:
            raise zigpy.exceptions.DeliveryError(
                "Cannot send a packet to a device without a known IEEE address"
            )

        send_req = self._api.tx_explicit(
            long_addr,
            short_addr,
            packet.src_ep or 0,
            packet.dst_ep or 0,
            packet.cluster_id,
            packet.profile_id,
            packet.radius,
            tx_opts,
            packet.data.serialize(),
        )

        try:
            v = await asyncio.wait_for(send_req, timeout=TIMEOUT_TX_STATUS)
        except asyncio.TimeoutError:
            raise zigpy.exceptions.DeliveryError(
                "Timeout waiting for ACK", status=TXStatus.NETWORK_ACK_FAILURE
            )

        if v != TXStatus.SUCCESS:
            raise zigpy.exceptions.DeliveryError(
                f"Failed to deliver packet: {v!r}", status=v
            )

    @zigpy.util.retryable_request()
    def remote_at_command(
        self, nwk, cmd_name, *args, apply_changes=True, encryption=True
    ):
        """Execute AT command on another XBee module in the network."""
        LOGGER.debug("Remote AT%s command: %s", cmd_name, args)
        options = zigpy.types.uint8_t(0)
        if apply_changes:
            options |= 0x02
        if encryption:
            options |= 0x10
        dev = self.get_device(nwk=nwk)
        return self._api._remote_at_command(dev.ieee, nwk, options, cmd_name, *args)

    async def permit_ncp(self, time_s=60):
        """Permit join."""
        assert 0 <= time_s <= 254
        await self._api._at_command("NJ", time_s)
        await self._api._at_command("AC")

    async def permit_with_link_key(
        self, node: EUI64, link_key: zigpy.types.KeyData, time_s: int = 500, key_type=0
    ):
        """Permits a new device to join with the given IEEE and link key."""
        assert 0x1E <= time_s <= 0xFFFF
        await self._api._at_command("KT", time_s)
        reserved = 0xFFFE
        # Key type:
        # 0 = Pre-configured Link Key (KY command of the joining device)
        # 1 = Install Code With CRC (I? command of the joining device)
        await self._api.register_joining_device(node, reserved, key_type, link_key)

    def handle_modem_status(self, status):
        """Handle changed Modem Status of the device."""
        LOGGER.info("Modem status update: %s (%s)", status.name, status.value)

    def handle_rx(
        self, src_ieee, src_nwk, src_ep, dst_ep, cluster_id, profile_id, rxopts, data
    ):
        """Handle receipt of Zigbee data from the device."""
        src = zigpy.types.AddrModeAddress(
            addr_mode=zigpy.types.AddrMode.NWK, address=src_nwk
        )

        dst = zigpy.types.AddrModeAddress(
            addr_mode=zigpy.types.AddrMode.NWK, address=self.state.node_info.nwk
        )

        if src == dst:
            LOGGER.info("handle_rx self addressed")

        try:
            self._device.update_last_seen()
        except KeyError:
            pass

        self.packet_received(
            zigpy.types.ZigbeePacket(
                src=src,
                src_ep=src_ep,
                dst=dst,
                dst_ep=dst_ep,
                tsn=None,
                profile_id=profile_id,
                cluster_id=cluster_id,
                data=zigpy.types.SerializableBytes(data),
            )
        )

    def neighbors_updated(
        self, ieee: zigpy.types.EUI64, neighbors: list[zdo_t.Neighbor]
    ) -> None:
        """Neighbor update from Mgmt_Lqi_req."""
        for neighbor in neighbors:
            if neighbor.relationship == zdo_t.Neighbor.Relationship.Parent:
                device = self.get_device(ieee=ieee)
                device.radio_details(lqi=neighbor.lqi)

            elif neighbor.relationship == zdo_t.Neighbor.Relationship.Child:
                try:
                    child_device = self.get_device(ieee=neighbor.ieee)
                    child_device.radio_details(lqi=neighbor.lqi)
                except KeyError:
                    LOGGER.warning("Unknown device %r", neighbor.ieee)

    def routes_updated(
        self, ieee: zigpy.types.EUI64, routes: list[zdo_t.Route]
    ) -> None:
        """Route update from Mgmt_Rtg_req."""
        self.create_task(
            self._routes_updated(ieee, routes), f"routes_updated-ieee={ieee}"
        )

    async def _routes_updated(
        self, ieee: zigpy.types.EUI64, routes: list[zdo_t.Route]
    ) -> None:
        """Get RSSI for adjacent routers on Route update from Mgmt_Rtg_req."""
        for route in routes:
            if (
                route.DstNWK == self.state.node_info.nwk
                and route.NextHop == self.state.node_info.nwk
                and route.RouteStatus == zdo_t.RouteStatus.Active
            ):
                device = self.get_device(ieee=ieee)
                rssi = await self._api._at_command("DB")
                device.radio_details(rssi=-rssi)
                break


class XBeeCoordinator(zigpy.quirks.CustomDevice):
    """Zigpy Device representing Coordinator."""

    class XBeeGroup(zigpy.quirks.CustomCluster, Groups):
        """XBeeGroup custom cluster."""

        cluster_id = 0x0006

    class XBeeGroupResponse(zigpy.quirks.CustomCluster, Groups):
        """XBeeGroupResponse custom cluster."""

        cluster_id = 0x8006
        ep_attribute = "xbee_groups_response"

        client_commands = {
            **Groups.client_commands,
            0x04: foundation.ZCLCommandDef(
                "remove_all_response",
                {"status": foundation.Status},
                direction=foundation.Direction.Client_to_Server,
            ),
        }

    def __init__(self, *args, **kwargs):
        """Initialize instance."""

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
