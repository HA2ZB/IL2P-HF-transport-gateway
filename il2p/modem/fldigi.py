from __future__ import annotations

import time
import xmlrpc.client

from .base import ModemStatus, TxOptions


class FldigiXmlRpcModem:
    def __init__(self, url: str = "http://127.0.0.1:7362") -> None:
        self.url = url
        self.rpc = xmlrpc.client.ServerProxy(url, allow_none=True)

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
        return ModemStatus(name=name, trx=trx, carrier=carrier)

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
        self.rpc.main.set_rxid(bool(auto_detect_mode))

    def return_to_rx(self) -> None:
        self.rpc.main.rx()

    def clear_rx(self) -> None:
        try:
            self.rpc.text.clear_rx()
        except Exception:
            # Some fldigi builds/XML-RPC versions may not expose clear_rx.
            try:
                self.rpc.text.get_rx()
            except Exception:
                pass

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
        self.rpc.text.clear_tx()
        self.rpc.text.add_tx(text)
        self.rpc.main.tx()
        # fldigi should return to RX when the queued text is sent, but explicitly
        # ask for RX after the transmit queue has drained / state changes back.
        while True:
            try:
                if self.rpc.main.get_trx_state() == "RX":
                    break
            except Exception:
                break
            time.sleep(0.2)
        if options.return_to_rx:
            try:
                self.return_to_rx()
            except Exception:
                pass
        if options.rx_resync_delay_s > 0:
            time.sleep(options.rx_resync_delay_s)
        self.clear_rx()

    def rx_text(self) -> str:
        data = self.rpc.text.get_rx()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)
