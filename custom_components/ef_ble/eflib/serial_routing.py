import dataclasses
from dataclasses import dataclass
from typing import ClassVar

from .packet import Packet, PacketV4


@dataclass(slots=True)
class RoutingEnvelope:
    flags: int
    cmd_set: int
    cmd_id: int
    seq: int
    src: int
    dst: int
    dsrc: int = 1
    ddst: int = 1

    PREFIX: ClassVar[bytes] = b"\x21\x01\x40\x03\x03"
    LEN: ClassVar[int] = 13

    @classmethod
    def from_bytes(cls, data: bytes) -> "RoutingEnvelope | None":
        if len(data) < cls.LEN or not data.startswith(cls.PREFIX):
            return None

        flags, cmd_set, cmd_id, seq, src, dsrc, dst, ddst = data[5 : cls.LEN]
        return cls(flags, cmd_set, cmd_id, seq, src, dst, dsrc, ddst)

    def to_bytes(self) -> bytes:
        return self.PREFIX + bytes(
            [
                self.flags,
                self.cmd_set,
                self.cmd_id,
                self.seq,
                self.src,
                self.dsrc,
                self.dst,
                self.ddst,
            ]
        )


class SerialRouting:
    HEADER_LEN: ClassVar[int] = 22
    SERIAL_FRAGMENT_LEN: ClassVar[int] = 9
    _WRITE_ENVELOPE_PREFIX: ClassVar[bytes] = b"\x40\x03\x03"

    def __init__(
        self,
        serial: str,
        *,
        cmd_set: int,
        cmd_id: int,
        dst: int,
        fallback_dst: int,
        src: int = 0x21,
        cmd_flags: int = 0x11,
        sequenced_writes: bool = False,
    ) -> None:
        self._serial = serial
        self._cmd_set = cmd_set
        self._cmd_id = cmd_id
        self._dst = dst
        self._fallback_dst = fallback_dst
        self._src = src
        self._cmd_flags = cmd_flags
        self._sequenced_writes = sequenced_writes
        self._post_template: PacketV4 | None = None
        self._envelope_template: bytes | None = None
        self._write_seq = 0x20

    @classmethod
    def split(cls, payload: bytes) -> tuple[str, bytes]:
        serial = payload[: cls.SERIAL_FRAGMENT_LEN].decode("ascii", errors="replace")
        return serial, payload[cls.HEADER_LEN :]

    @classmethod
    def envelope(cls, payload: bytes) -> RoutingEnvelope | None:
        return RoutingEnvelope.from_bytes(
            payload[cls.SERIAL_FRAGMENT_LEN : cls.HEADER_LEN]
        )

    def remember_post(self, packet: PacketV4) -> None:
        self._post_template = packet
        self._envelope_template = packet.payload[
            self.SERIAL_FRAGMENT_LEN : self.HEADER_LEN
        ]

    def _envelope_flags(self) -> int:
        envelope = (
            RoutingEnvelope.from_bytes(self._envelope_template)
            if self._envelope_template is not None
            else None
        )
        return envelope.flags if envelope is not None else 0

    def _next_seq(self) -> int:
        if not self._sequenced_writes:
            return 0
        self._write_seq = (self._write_seq + 1) & 0xFF
        return self._write_seq

    def write_packet(self, body: bytes, cmd_id: int | None = None) -> Packet | PacketV4:
        cmd_id = self._cmd_id if cmd_id is None else cmd_id
        if self._post_template is None:
            return Packet(
                self._src,
                self._fallback_dst,
                self._cmd_set,
                cmd_id,
                body,
                0x01,
                0x01,
                0x13,
            )

        envelope = (
            self._WRITE_ENVELOPE_PREFIX
            + bytes(
                [
                    self._envelope_flags(),
                    self._cmd_set,
                    cmd_id,
                    self._next_seq(),
                    self._src,
                    0x01,
                    self._dst,
                    0x01,
                ]
            )
        )
        serial9 = self._serial[-self.SERIAL_FRAGMENT_LEN :].encode("ascii")
        return dataclasses.replace(
            self._post_template,
            cmd_flags=self._cmd_flags,
            is_ack=True,
            is_rw_cmd=False,
            payload=serial9 + self._serial.encode("ascii") + envelope + body,
        )
