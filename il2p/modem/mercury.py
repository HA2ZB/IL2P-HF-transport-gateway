"""Mercury v1.9.15 KISS/TCP broadcast message adapter (CMD_DATA=0x02).

    The payload is binary IL2P, not a preframed Mercury modem packet (0x03).
    Mercury owns its over-air header/length prefix and strips them on RX.
"""
from __future__ import annotations

from collections import deque
import select
import socket
import threading

from .base import ModemStatus, TxOptions
from .kiss import KissDecoder, encode_kiss

# v1.9.15 datalink_broadcast/bcast_modes.h; message overhead is 3 bytes.
MODE_FRAME_SIZES = (510, 126, 14, 54, 14, 3, 30, 30, 14, 1180, 1213)
MODE_NAMES = ("DATAC1", "DATAC3", "DATAC0", "DATAC4", "DATAC13", "DATAC14",
              "FSK_LDPC", "DATAC15", "DATAC16", "DATAC17", "QAM16C2")


class MercuryKissTcpModem:
    def __init__(self, host: str = "127.0.0.1", port: int = 8100, *,
                 mode_index: int = 1, timeout_s: float = 3.0) -> None:
        if not host or not 1 <= port <= 65535:
            raise ValueError("Mercury requires a host and TCP port in 1..65535")
        if not 0 <= mode_index < len(MODE_FRAME_SIZES):
            raise ValueError("Mercury mode_index must be in 0..10")
        if timeout_s <= 0:
            raise ValueError("Mercury timeout_s must be positive")
        self.host, self.port = host, port
        self.mode_index, self.timeout_s = mode_index, timeout_s
        self.max_payload_bytes = MODE_FRAME_SIZES[mode_index] - 3
        self._socket: socket.socket | None = None
        self._decoder = KissDecoder()
        self._frames: deque[tuple[int, bytes] | ValueError] = deque()
        self._lock = threading.RLock()

    def connect(self) -> None:
        """Open TCP only; never send a probe, control command or radio data."""
        with self._lock:
            if self._socket is None:
                sock = socket.create_connection((self.host, self.port), self.timeout_s)
                sock.settimeout(self.timeout_s)
                self._socket = sock

    def close(self) -> None:
        with self._lock:
            if self._socket is not None:
                self._socket.close()
                self._socket = None
            self._decoder.reset()
            self._frames.clear()

    def status(self) -> ModemStatus:
        with self._lock:
            return ModemStatus(
                name="Mercury", backend="mercury", state="connected" if self._socket else "disconnected",
                details={"host": self.host, "port": self.port, "transport": "kiss_tcp_broadcast",
                         "configured_mode": MODE_NAMES[self.mode_index], "mode_index": self.mode_index,
                         "max_il2p_bytes": self.max_payload_bytes},
            )

    def set_mode(self, mode_name: str) -> None:
        raise NotImplementedError("KISS broadcast cannot set/query Mercury mode; configure Mercury externally")

    def send(self, data: bytes, options: TxOptions | None = None) -> None:
        if options is not None and (options.coding != "none" or options.mode_name):
            raise ValueError("Mercury requires coding=none and externally configured mode")
        if not data or len(data) > self.max_payload_bytes:
            raise ValueError(f"Mercury IL2P frame must be 1..{self.max_payload_bytes} bytes for configured mode")
        packet = encode_kiss(data, command=0x02)
        with self._lock:
            self.connect()
            try:
                self._socket.sendall(packet)
            except OSError:
                # A partial write is ambiguous: never reconnect and replay TX.
                self.close()
                raise

    def receive(self) -> bytes:
        with self._lock:
            if not self._frames:
                self.connect()
                try:
                    if not select.select([self._socket], [], [], 0)[0]:
                        return b""
                    chunk = self._socket.recv(4096)
                    if not chunk:
                        raise ConnectionError("Mercury KISS TCP connection closed")
                except OSError:
                    self.close()
                    raise
                self._frames.extend(self._decoder.feed(chunk))
            while self._frames:
                frame = self._frames.popleft()
                if isinstance(frame, ValueError):
                    raise frame
                command, payload = frame
                # Port nibble is not an IL2P field. This backend uses port 0.
                if command >> 4 or (command & 0x0F) >= 4:
                    continue
                if command != 0x02:
                    raise ValueError(f"Unexpected Mercury KISS data command: 0x{command:02x}")
                if not payload:
                    raise ValueError("Empty Mercury KISS data frame")
                return payload
            return b""
