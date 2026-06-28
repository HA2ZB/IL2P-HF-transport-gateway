from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RSStats:
    header_corrected_symbols: int = 0
    payload_corrected_symbols: int = 0
    payload_block_corrected_symbols: list[int] = field(default_factory=list)


@dataclass(slots=True)
class EncodedIL2PFrame:
    ax25_frame: bytes
    raw_header: bytes
    encoded_header: bytes
    encoded_payload: bytes
    il2p_frame: bytes

    def as_legacy_tuple(self) -> tuple[bytes, bytes, bytes, bytes, bytes]:
        return (
            self.ax25_frame,
            self.raw_header,
            self.encoded_header,
            self.encoded_payload,
            self.il2p_frame,
        )


@dataclass(slots=True)
class DecodedIL2PFrame:
    src: str
    src_ssid: int
    dst: str
    dst_ssid: int
    pid: int
    payload_len: int
    fec_level: int
    header_raw: bytes
    header_scrambled: bytes
    payload_raw: bytes
    aprs_text: str
    header: dict[str, Any]
    rs: RSStats = field(default_factory=RSStats)

    def as_legacy_dict(self) -> dict[str, Any]:
        return {
            "src": self.src,
            "src_ssid": self.src_ssid,
            "dst": self.dst,
            "dst_ssid": self.dst_ssid,
            "pid": self.pid,
            "payload_len": self.payload_len,
            "fec_level": self.fec_level,
            "header_raw": self.header_raw,
            "header_scrambled": self.header_scrambled,
            "payload_raw": self.payload_raw,
            "aprs_text": self.aprs_text,
            "header": self.header,
            "rs": {
                "header_corrected_symbols": self.rs.header_corrected_symbols,
                "payload_corrected_symbols": self.rs.payload_corrected_symbols,
                "payload_block_corrected_symbols": list(self.rs.payload_block_corrected_symbols),
            },
        }
