import pytest
from pytest_mock import MockerFixture

from custom_components.ef_ble.eflib import device_class_from_sn
from custom_components.ef_ble.eflib.devices.stream_ac_5000 import Device
from custom_components.ef_ble.eflib.packet import Packet, PacketV4
from custom_components.ef_ble.eflib.pb import es22_bkw_pb2
from custom_components.ef_ble.eflib.serial_routing import RoutingEnvelope, SerialRouting


@pytest.fixture
def device(mocker: MockerFixture):
    ble_dev = mocker.Mock()
    ble_dev.address = "AA:BB:CC:DD:EE:FF"
    return Device(ble_dev, mocker.MagicMock(), "ES22XXXXXXXXXXXX")


def _telemetry_packet(message: es22_bkw_pb2.DisplayPropertyUpload) -> bytes:
    return Packet(
        0x02,
        0x21,
        0xFE,
        0x27,
        message.SerializeToString(),
        0x01,
        0x01,
        0x03,
    ).to_bytes()


def _telemetry_message() -> es22_bkw_pb2.DisplayPropertyUpload:
    message = es22_bkw_pb2.DisplayPropertyUpload()
    message.system_sub_dev_energy_flow_detail.dev_energy_flow_detail.add(
        inv_pwr=311.43,
        bp_pwr=-300.32,
        on_grid_pwr=12.4,
    )
    message.system_sub_dev_battery_report.system_sub_dev_battery_info.add(
        sn="ES22XXXXXXXXXXXX", soc=56
    )
    message.battery_info_report.battery_info_item.add(soc=55, cell_max_temp=39)
    message.sys_energy_stream_report.load_pwr = 300
    message.sys_battery_info_report.charge_remain_time = 17
    message.sys_battery_info_report.discharge_remain_time = 83
    message.energy_flow_from_to_detail.bp_to_load = 290
    message.energy_flow_from_to_detail.grid_to_load = 10
    return message


def test_device_class_recognizes_es22_serials():
    assert device_class_from_sn(b"ES22XXXXXXXXXXXX") is Device


async def test_parses_stream_ac_5000_telemetry(device):
    packet = await device.packet_parse(_telemetry_packet(_telemetry_message()))
    assert await device.data_parse(packet)

    assert device.battery_level == 56
    assert device.battery_level_main == 55
    assert device.cell_temperature == 39
    assert device.battery_power == pytest.approx(-311.43)
    assert device.grid_power == pytest.approx(12.4)
    assert device.load_system == 300
    assert device.load_from_battery == 290
    assert device.load_from_grid == 10
    assert device.remaining_time_charging == 17
    assert device.remaining_time_discharging == 83


async def test_parses_unobfuscated_serial_routed_v4_telemetry(device):
    serial = device.serial_number
    envelope = RoutingEnvelope(
        flags=0x2E,
        cmd_set=0xFE,
        cmd_id=0x27,
        seq=0x20,
        src=0x02,
        dst=0x21,
    )
    routed_payload = (
        serial[-9:].encode("ascii")
        + envelope.to_bytes()
        + _telemetry_message().SerializeToString()
    )
    raw = PacketV4(
        src=0x02,
        dst=0x21,
        cmd_set=0xFE,
        cmd_id=0x27,
        payload=routed_payload,
        sentinel=True,
    ).to_bytes()

    packet = await device.packet_parse(raw)

    assert isinstance(packet, PacketV4)
    assert packet.sentinel
    assert not packet.obfuscated
    assert await device.data_parse(packet)
    assert device.battery_level == 56
    assert device.battery_power == pytest.approx(-311.43)


def test_ac_port_control_uses_module_addressed_source(device):
    routing = SerialRouting(
        device.serial_number,
        cmd_set=0xFE,
        cmd_id=0x26,
        dst=0x02,
        fallback_dst=0x02,
        sequenced_writes=True,
    )
    envelope = RoutingEnvelope(
        flags=0x2E,
        cmd_set=0xFE,
        cmd_id=0x27,
        seq=0x20,
        src=0x02,
        dst=0x21,
    )
    post = PacketV4(
        src=0x02,
        dst=0x21,
        cmd_set=0xFE,
        cmd_id=0x27,
        payload=device.serial_number[-9:].encode("ascii") + envelope.to_bytes(),
        sentinel=True,
    )
    routing.remember_post(post)

    packet = routing.write_packet(b"ac-port-setting")

    assert isinstance(packet, PacketV4)
    assert packet.cmd_flags == 0x10
