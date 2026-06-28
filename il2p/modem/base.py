from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class TxOptions:
    mode_name: str | None = None
    announce_mode: bool = True       # fldigi TXID / RSID
    auto_detect_mode: bool = False   # fldigi RXID
    strip_newlines: bool = True
    return_to_rx: bool = True
    rx_resync_delay_s: float = 0.4


class Modem(Protocol):
    def status(self) -> ModemStatus: ...
    def set_mode(self, mode_name: str) -> None: ...
    def set_id_policy(self, *, announce_mode: bool, auto_detect_mode: bool) -> None: ...
    def tx_text(self, text: str, options: TxOptions | None = None) -> None: ...
    def rx_text(self) -> str: ...
