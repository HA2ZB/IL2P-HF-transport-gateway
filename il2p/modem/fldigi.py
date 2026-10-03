from __future__ import annotations

import re
import time
import xmlrpc.client
from collections import deque

from il2p.framing.text import END_TAG, decode_frame_text, encode_frame_text, extract_frame_candidates

from .base import ModemStatus, TxOptions


class FldigiXmlRpcModem:
    def __init__(self, url: str = "http://127.0.0.1:7362") -> None:
        self._rx_buffer = ""
        self._rx_frames: deque[bytes | ValueError] = deque()
        self.url = url
        self.rpc = xmlrpc.client.ServerProxy(url, allow_none=True)

    @staticmethod
    def frame_text(data: bytes, options: TxOptions | None = None) -> str:
        options = options or TxOptions()
        if options.coding not in {"base32", "base64"}:
            raise ValueError("fldigi requires base32 or base64 coding")
        return encode_frame_text(data, coding=options.coding, callsign=options.callsign)

    def send(self, data: bytes, options: TxOptions | None = None) -> None:
        self.tx_text(self.frame_text(data, options), options)

    def receive(self) -> bytes:
        """Poll packet RX; do not mix this with rx_text on the same instance."""
        if not self._rx_frames:
            self._rx_buffer += self.rx_text()
            compact = "".join(self._rx_buffer.split())
            consumed = 0
            for candidate in extract_frame_candidates(compact):
                if END_TAG not in candidate:
                    break
                consumed = compact.find(candidate, consumed) + len(candidate)
                try:
                    self._rx_frames.append(decode_frame_text(candidate))
                except ValueError as error:
                    self._rx_frames.append(error)
            self._rx_buffer = compact[consumed:][-20000:]
        if not self._rx_frames:
            return b""
        frame = self._rx_frames.popleft()
        if isinstance(frame, ValueError):
            raise frame
        return frame

    def status(self) -> ModemStatus:
        try:
            name = str(self.rpc.modem.get_name())
        except Exception:
            name = "UNKNOWN"
        try:
            trx = str(self.rpc.main.get_trx_state())
        except Exception:
            trx = "?"
        try:
            carrier = str(self.rpc.main.get_wfcarrier())
        except Exception:
            carrier = "N/A"
        try:
            status1 = str(self.rpc.main.get_status1())
        except Exception:
            status1 = None
        try:
            status2 = str(self.rpc.main.get_status2())
        except Exception:
            status2 = None
        snr = re.search(r"s/n:\s*([-+]?\d+(?:\.\d+)?)\s*dB", status1 or "", re.IGNORECASE)
        return ModemStatus(
            name=name, trx=trx, carrier=carrier, status1=status1, status2=status2,
            backend="fldigi", mode=name, state=trx,
            snr_db=float(snr.group(1)) if snr else None,
            details={"carrier": carrier, "status1": status1, "status2": status2},
        )

    def set_mode(self, mode_name: str) -> None:
        """Set fldigi modem by visible fldigi mode name.

        fldigi XML-RPC installations differ slightly across versions, so keep a
        narrow fallback chain. The configured value should be the exact fldigi
        name visible in the modem selector, e.g. "Olivia 4/250".
        """
        last: Exception | None = None
        for call in (
            lambda: self.rpc.modem.set_by_name(mode_name),
            lambda: self.rpc.modem.set_by_id(mode_name),
        ):
            try:
                call()
                return
            except Exception as e:
                last = e
        raise RuntimeError(f"fldigi mode set failed for {mode_name!r}: {last}")

    def set_id_policy(self, *, announce_mode: bool, auto_detect_mode: bool) -> None:
        # TXID = send RSID/TXID at the beginning of our transmission.
        # RXID = allow fldigi to auto-detect incoming mode changes. For fixed
        # IL2P links this is normally disabled because the application layer
        # sets the expected mode explicitly.
        self.rpc.main.set_txid(bool(announce_mode))
        # self.rpc.main.set_rxid(bool(auto_detect_mode))

    def return_to_rx(self) -> None:
        self.rpc.main.rx()

    def clear_rx(self) -> None:
        self._rx_buffer = ""
        self._rx_frames.clear()
        try:
            self.rpc.text.clear_rx()
        except Exception:
            # Some fldigi builds/XML-RPC versions may not expose clear_rx.
            try:
                self.rpc.text.get_rx()
            except Exception:
                pass

    def _coerce_rpc_text(self, data: object) -> str:
        if data is None:
            return ""
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        if isinstance(data, xmlrpc.client.Binary):
            return data.data.decode("utf-8", errors="replace")
        return str(data)

    def _get_transmitted_text(self) -> str:
        """Return text fldigi has actually transmitted since last query.

        fldigi's tx.get_data() is incremental: each call returns only the TX
        data transmitted since the previous call. We use it to wait until the
        complete queued text has really gone out before forcing fldigi back to
        RX.
        """
        return self._coerce_rpc_text(self.rpc.tx.get_data())

    def _wait_until_text_transmitted(
        self,
        text: str,
        *,
        timeout_s: float = 300.0,
        poll_s: float = 0.25,
    ) -> bool:
        sent = ""
        deadline = time.time() + timeout_s

        while time.time() < deadline:
            try:
                chunk = self._get_transmitted_text()
            except Exception:
                return False
            if chunk:
                sent += chunk
                if text in sent:
                    return True
            time.sleep(poll_s)

        return False

    def tx_text(self, text: str, options: TxOptions | None = None) -> None:
        options = options or TxOptions()
        if options.strip_newlines:
            text = text.replace("\r", "").replace("\n", "")
        if options.mode_name:
            self.set_mode(options.mode_name)
        self.set_id_policy(
            announce_mode=options.announce_mode,
            auto_detect_mode=options.auto_detect_mode,
        )

        # Flush fldigi's incremental TX monitor before starting this transmission.
        # This prevents earlier/manual TX data from satisfying the completion test.
        try:
            self._get_transmitted_text()
        except Exception:
            pass

        self.rpc.text.clear_tx()
        self.rpc.text.add_tx(text)
        self.rpc.main.tx()

        timeout_s = float(getattr(options, "tx_timeout_s", 300.0))
        poll_s = float(getattr(options, "tx_poll_s", 0.25))
        transmitted = self._wait_until_text_transmitted(
            text,
            timeout_s=timeout_s,
            poll_s=poll_s,
        )

        if options.return_to_rx:
            try:
                self.return_to_rx()
            except Exception:
                pass

        if not transmitted:
            # Do not raise here: returning to RX is more important in field use.
            # The REST layer can later expose this as a warning/diagnostic.
            pass

        if options.rx_resync_delay_s > 0:
            time.sleep(options.rx_resync_delay_s)
        self.clear_rx()

    def rx_text(self) -> str:
        # rx.get_data() returns only newly received text in fldigi builds that
        # expose it. text.get_rx() is kept as a fallback for older XML-RPC APIs.
        try:
            data = self.rpc.rx.get_data()
        except Exception:
            data = self.rpc.text.get_rx()
        return self._coerce_rpc_text(data)
