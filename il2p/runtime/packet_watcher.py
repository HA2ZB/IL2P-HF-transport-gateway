"""Binary packet RX, alongside the existing fldigi text watcher."""
from __future__ import annotations

from il2p.codec import decode_il2p_frame
from il2p.modem import ModemBackend
from .rx import LinkState, RxDiagnostics, RxStore
from .watcher import FldigiWatcherService, WatcherStats


class PacketRxWatcher:
    def __init__(self, store: RxStore, *, mode: str | None = None) -> None:
        self.store, self.mode = store, mode
        self.stats = WatcherStats()

    def invalid(self, error: Exception, *, data: bytes | None = None) -> int:
        self.stats.invalid_frames += 1
        self.stats.last_error = str(error)
        return self.store.append_result(
            valid=False, coding="none", mode=self.mode, reason=str(error),
            il2p_len=len(data) if data is not None else None,
            diagnostics=RxDiagnostics(raw={"backend": "mercury"}),
        ).id

    def feed(self, data: bytes) -> int:
        self.stats.chunks_seen += 1
        self.stats.candidates_seen += 1
        self.store.set_state(LinkState.DECODING, "decoding binary IL2P frame")
        try:
            decoded = decode_il2p_frame(data)
            result = self.store.append_result(
                valid=True, coding="none", mode=self.mode,
                src=f"{decoded['src']}-{decoded['src_ssid']}",
                dst=f"{decoded['dst']}-{decoded['dst_ssid']}",
                aprs_text=decoded["aprs_text"], fec=decoded["fec_level"], il2p_len=len(data),
                diagnostics=RxDiagnostics(raw={"backend": "mercury"}),
            )
            self.stats.valid_frames += 1
            return result.id
        except Exception as error:
            return self.invalid(error, data=data)
        finally:
            self.store.set_state(LinkState.RX_NOISE, "binary RX watcher waiting")


class PacketWatcherService(FldigiWatcherService):
    """Reuse watcher lifecycle; packet polling never consumes fldigi text."""

    def __init__(self, source: ModemBackend, watcher: PacketRxWatcher, *, poll_s: float = 0.2) -> None:
        super().__init__(source, watcher, poll_s=poll_s)

    def poll_once(self) -> None:
        try:
            data = self.source.receive()
        except ValueError as error:
            self.watcher.invalid(error)
            self.watcher.store.set_state(LinkState.RX_NOISE, "invalid KISS frame consumed")
            return
        if data:
            self.watcher.feed(data)

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.paused:
                try:
                    self.poll_once()
                except Exception as error:
                    self.watcher.stats.last_error = str(error)
                    self.watcher.store.set_state(LinkState.ERROR, f"binary RX watcher error: {error}")
                    if self._stop.wait(max(1.0, self.poll_s)):
                        break
            self._stop.wait(self.poll_s)

    def stop(self, timeout: float = 5.0) -> None:
        super().stop(timeout)
        if self.running:
            raise RuntimeError("Binary RX watcher did not stop before timeout")
        close = getattr(self.source, "close", None)
        if close:
            close()
