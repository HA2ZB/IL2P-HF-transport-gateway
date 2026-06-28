from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
import time
from typing import Any


class LinkState(StrEnum):
    IDLE = "IDLE"
    RX_NOISE = "RX_NOISE"
    FRAME_CANDIDATE = "FRAME_CANDIDATE"
    DECODING = "DECODING"
    TX_REQUESTED = "TX_REQUESTED"
    TX_ENCODING = "TX_ENCODING"
    TX_ACTIVE = "TX_ACTIVE"
    RX_RESYNC = "RX_RESYNC"
    ERROR = "ERROR"


@dataclass(slots=True)
class RxDiagnostics:
    snr_last: float | None = None
    snr_min: float | None = None
    snr_avg: float | None = None
    freq_offset_last_hz: float | None = None
    header_rs_corrected_symbols: int | None = None
    payload_rs_corrected_symbols: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "snr_last": self.snr_last,
            "snr_min": self.snr_min,
            "snr_avg": self.snr_avg,
            "freq_offset_last_hz": self.freq_offset_last_hz,
            "header_rs_corrected_symbols": self.header_rs_corrected_symbols,
            "payload_rs_corrected_symbols": self.payload_rs_corrected_symbols,
            "raw": self.raw,
        }


@dataclass(slots=True)
class RxResult:
    id: int
    ts: float
    valid: bool
    coding: str | None = None
    mode: str | None = None
    src: str | None = None
    dst: str | None = None
    fec: int | None = None
    aprs_text: str | None = None
    il2p_len: int | None = None
    raw_text_excerpt: str | None = None
    reason: str | None = None
    diagnostics: RxDiagnostics = field(default_factory=RxDiagnostics)

    def as_dict(self, detailed: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "ts": self.ts,
            "valid": self.valid,
            "coding": self.coding,
            "mode": self.mode,
            "src": self.src,
            "dst": self.dst,
            "fec": self.fec,
            "aprs_text": self.aprs_text,
            "il2p_len": self.il2p_len,
            "reason": self.reason,
        }
        if detailed:
            data["raw_text_excerpt"] = self.raw_text_excerpt
            data["diagnostics"] = self.diagnostics.as_dict()
        return data


class RxStore:
    """In-memory RX result queue for REST polling.

    The watcher owns decoding and pushes valid/invalid results here. REST only
    reads status/results. IDs are local, monotonically increasing API IDs; they
    are not IL2P protocol fields.
    """

    def __init__(self, maxlen: int = 500) -> None:
        self.state = LinkState.IDLE
        self.state_reason: str | None = None
        self.results: deque[RxResult] = deque(maxlen=maxlen)
        self.next_result_id = 1
        self.tx_active = False
        self.rx_active = True

    @property
    def last_result_id(self) -> int:
        return self.results[-1].id if self.results else 0

    def set_state(self, state: LinkState | str, reason: str | None = None) -> None:
        self.state = LinkState(str(state))
        self.state_reason = reason
        self.tx_active = self.state in {LinkState.TX_REQUESTED, LinkState.TX_ENCODING, LinkState.TX_ACTIVE}
        self.rx_active = self.state not in {LinkState.TX_REQUESTED, LinkState.TX_ENCODING, LinkState.TX_ACTIVE, LinkState.RX_RESYNC}

    def append_result(self, *, valid: bool, **kwargs: Any) -> RxResult:
        result = RxResult(id=self.next_result_id, ts=time.time(), valid=valid, **kwargs)
        self.next_result_id += 1
        self.results.append(result)
        return result

    def list_results(self, since: int = 0, limit: int = 50, detailed: bool = False) -> list[dict[str, Any]]:
        return [r.as_dict(detailed=detailed) for r in self.results if r.id > since][-limit:]

    def get_result(self, result_id: int) -> RxResult | None:
        for result in self.results:
            if result.id == result_id:
                return result
        return None
