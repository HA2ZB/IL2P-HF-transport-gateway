from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from il2p.codec import decode_il2p_frame
from il2p.framing import BEGIN_TAG, END_TAG, FramingError, decode_frame_text, extract_frame_candidates
from il2p.modem.base import ModemStatus
from il2p.runtime.rx import LinkState, RxDiagnostics, RxStore


class RxTextSource(Protocol):
    def rx_text(self) -> str: ...
    def status(self) -> ModemStatus: ...


_SNR_RE = re.compile(r"s/n:\s*([-+]?\d+(?:\.\d+)?)\s*dB", re.IGNORECASE)
_FO_RE = re.compile(r"f/o\s*([-+]?\d+(?:\.\d+)?)\s*Hz", re.IGNORECASE)


def parse_snr_db(status: str | None) -> float | None:
    if not status:
        return None
    m = _SNR_RE.search(str(status))
    return None if not m else float(m.group(1))


def parse_freq_offset_hz(status: str | None) -> float | None:
    if not status:
        return None
    m = _FO_RE.search(str(status))
    return None if not m else float(m.group(1))


@dataclass(slots=True)
class WatcherStats:
    chunks_seen: int = 0
    candidates_seen: int = 0
    valid_frames: int = 0
    invalid_frames: int = 0
    last_error: str | None = None


class RxWatcher:
    """Decode IL2P text frames from an RX character stream into an RxStore.

    This is deliberately independent from FastAPI and from fldigi. The REST
    layer can poll RxStore, and fldigi is only one possible RxTextSource.
    """

    def __init__(
        self,
        store: RxStore,
        *,
        mode: str | None = None,
        max_buffer: int = 20000,
        candidate_timeout_s: float = 45.0,
    ) -> None:
        self.store = store
        self.mode = mode
        self.max_buffer = max_buffer
        self.candidate_timeout_s = candidate_timeout_s
        self.candidate_started_at: float | None = None
        self.buffer = ""
        self.processed_candidates: set[str] = set()
        self.snr_samples: list[float] = []
        self.frame_snr_samples: list[float] = []
        self.frame_active = False
        self.last_status1: str | None = None
        self.last_status2: str | None = None
        self.stats = WatcherStats()

    def reset_frame_tracking(self) -> None:
        self.frame_active = False
        self.candidate_started_at = None
        self.frame_snr_samples = []

    def tick(self) -> None:
        """Advance time-based watcher state even if no new RX text arrives."""
        if (
            self.frame_active
            and self.candidate_started_at is not None
            and time.time() - self.candidate_started_at > self.candidate_timeout_s
        ):
            self.buffer = ""
            self.reset_frame_tracking()
            if self.store.state == LinkState.FRAME_CANDIDATE:
                self.store.set_state(LinkState.RX_NOISE, "frame candidate timeout")

    def update_status(self, *, status1: str | None = None, status2: str | None = None) -> None:
        self.last_status1 = status1 if status1 is not None else self.last_status1
        self.last_status2 = status2 if status2 is not None else self.last_status2
        snr = parse_snr_db(self.last_status1)
        if snr is not None:
            self.snr_samples.append(snr)
            if len(self.snr_samples) > 1000:
                self.snr_samples = self.snr_samples[-1000:]
            if self.frame_active:
                self.frame_snr_samples.append(snr)

    def diagnostics(self) -> RxDiagnostics:
        frame_samples = self.frame_snr_samples or []
        snr_samples = frame_samples or self.snr_samples
        return RxDiagnostics(
            snr_last=parse_snr_db(self.last_status1),
            snr_min=(min(snr_samples) if snr_samples else None),
            snr_avg=(sum(snr_samples) / len(snr_samples) if snr_samples else None),
            freq_offset_last_hz=parse_freq_offset_hz(self.last_status2),
            raw={"status1_last": self.last_status1, "status2_last": self.last_status2},
        )

    def feed(self, chunk: str) -> list[int]:
        """Feed newly received text and return IDs of appended RxResult objects."""
        self.tick()
        if not chunk:
            return []
        self.stats.chunks_seen += 1
        self.buffer += chunk
        if len(self.buffer) > self.max_buffer:
            self.buffer = self.buffer[-self.max_buffer:]

        compact = "".join(self.buffer.split()).upper()
        if not self.frame_active and (BEGIN_TAG in compact or "LEN" in compact):
            self.frame_active = True
            self.candidate_started_at = time.time()
            self.frame_snr_samples = []
            self.store.set_state(LinkState.FRAME_CANDIDATE, "IL2P-like RX text detected")

        appended: list[int] = []
        for candidate in extract_frame_candidates(self.buffer):
            key = candidate[-512:]
            if key in self.processed_candidates:
                continue
            if END_TAG not in "".join(candidate.split()).upper():
                # Keep waiting for the rest of the frame.
                continue
            self.processed_candidates.add(key)
            appended.append(self._process_candidate(candidate))

        if appended:
            self.reset_frame_tracking()
            self.store.set_state(LinkState.RX_NOISE, "RX watcher waiting")
        elif self.store.state not in {LinkState.TX_ACTIVE, LinkState.TX_ENCODING, LinkState.TX_REQUESTED, LinkState.RX_RESYNC}:
            self.store.set_state(LinkState.RX_NOISE if not self.frame_active else LinkState.FRAME_CANDIDATE)
        return appended

    def _process_candidate(self, candidate: str) -> int:
        self.stats.candidates_seen += 1
        self.store.set_state(LinkState.DECODING, "decoding RX frame candidate")
        coding = "auto"
        try:
            il2p = decode_frame_text(candidate)
            decoded = decode_il2p_frame(il2p)
            result = self.store.append_result(
                valid=True,
                coding=coding,
                mode=self.mode,
                src=f"{decoded['src']}-{decoded['src_ssid']}",
                dst=f"{decoded['dst']}-{decoded['dst_ssid']}",
                aprs_text=decoded["aprs_text"],
                fec=decoded["fec_level"],
                il2p_len=len(il2p),
                raw_text_excerpt=candidate[:200],
                diagnostics=self.diagnostics(),
            )
            self.stats.valid_frames += 1
            return result.id
        except Exception as e:
            result = self.store.append_result(
                valid=False,
                coding=coding,
                mode=self.mode,
                raw_text_excerpt=candidate[:200],
                reason=str(e),
                diagnostics=self.diagnostics(),
            )
            self.stats.invalid_frames += 1
            self.stats.last_error = str(e)
            return result.id


class FldigiWatcherService:
    """Background service that polls fldigi RX and feeds RxWatcher."""

    def __init__(self, source: RxTextSource, watcher: RxWatcher, *, poll_s: float = 0.2) -> None:
        self.source = source
        self.watcher = watcher
        self.poll_s = poll_s
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._paused.clear()
        self._thread = threading.Thread(target=self._run, name="il2p-fldigi-rxwatch", daemon=True)
        self._thread.start()
        self.watcher.store.set_state(LinkState.IDLE, "RX watcher started")

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self.watcher.store.set_state(LinkState.IDLE, "RX watcher stopped")

    def pause(self, reason: str = "paused") -> None:
        self._paused.set()
        self.watcher.store.rx_active = False
        self.watcher.store.state_reason = reason

    def resume(self, reason: str = "resumed") -> None:
        self._paused.clear()
        self.watcher.store.set_state(LinkState.IDLE, reason)

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(self.poll_s)
                continue
            try:
                status = self.source.status()
                self.watcher.update_status(status1=getattr(status, "status1", None), status2=getattr(status, "status2", None))
                chunk = self.source.rx_text()
                if chunk:
                    self.watcher.feed(chunk)
                else:
                    self.watcher.tick()
            except Exception as e:
                self.watcher.stats.last_error = str(e)
                self.watcher.store.set_state(LinkState.ERROR, f"RX watcher error: {e}")
                time.sleep(max(1.0, self.poll_s))
            time.sleep(self.poll_s)
