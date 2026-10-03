from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class ModemStatus:
    name: str = "UNKNOWN"
    trx: str = "?"
    carrier: str = "N/A"
    txid: bool | None = None
    rxid: bool | None = None
    status1: str | None = None
    status2: str | None = None
    backend: str = "unknown"
    mode: str | None = None
    state: str | None = None
    snr_db: float | None = None
    bitrate_bps: int | None = None
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TxOptions:
    mode_name: str | None = None
    announce_mode: bool = True       # fldigi TXID / RSID
    auto_detect_mode: bool = False   # fldigi RXID
    strip_newlines: bool = True
    return_to_rx: bool = True
    rx_resync_delay_s: float = 0.4
    coding: str = "base64"
    callsign: str | None = None


class ModemBackend(Protocol):
    """Packet API: send one IL2P frame; receive one complete frame or b"".

    Adapters own transport framing and retain partial incoming data between
    polls. A malformed transport frame raises ValueError and is consumed so
    a subsequent poll can continue. send() does not imply application ACK.
    """

    def status(self) -> ModemStatus: ...
    def set_mode(self, mode_name: str) -> None: ...
    def send(self, data: bytes, options: TxOptions | None = None) -> None: ...
    def receive(self) -> bytes: ...


# Backward-compatible import name. Text helpers are adapter-specific.
Modem = ModemBackend
