"""Incremental KISS framing, independent of sockets and IL2P decoding."""
from __future__ import annotations

FEND, FESC, TFEND, TFESC = 0xC0, 0xDB, 0xDC, 0xDD


def encode_kiss(payload: bytes, command: int = 0x02) -> bytes:
    if not 0 <= command <= 255:
        raise ValueError("KISS command must be a byte")
    body = bytes([command]) + payload
    return bytes([FEND]) + body.replace(b"\xdb", b"\xdb\xdd").replace(b"\xc0", b"\xdb\xdc") + bytes([FEND])


class KissDecoder:
    """Keep partial frames; emit (command, payload) or consumed frame errors.

    Memory is bounded even without an ending delimiter. Repeated delimiters
    and leading noise are harmless. A closing FEND also starts the next frame.
    """

    def __init__(self, max_payload: int = 1213) -> None:
        if max_payload < 1:
            raise ValueError("max_payload must be positive")
        self.max_payload = max_payload
        self.reset()

    def reset(self) -> None:
        self._started = False
        self._body = bytearray()
        self._escaped = False
        self._error: str | None = None

    def feed(self, chunk: bytes) -> list[tuple[int, bytes] | ValueError]:
        frames: list[tuple[int, bytes] | ValueError] = []
        for byte in chunk:
            if byte == FEND:
                if self._started:
                    error = self._error or ("Incomplete KISS escape" if self._escaped else None)
                    if error:
                        frames.append(ValueError(error))
                    elif self._body:
                        frames.append((self._body[0], bytes(self._body[1:])))
                self._started = True
                self._body.clear()
                self._escaped = False
                self._error = None
                continue
            if not self._started or self._error:
                continue
            if self._escaped:
                self._escaped = False
                if byte == TFEND:
                    byte = FEND
                elif byte == TFESC:
                    byte = FESC
                else:
                    self._error = "Invalid KISS escape"
                    continue
            elif byte == FESC:
                self._escaped = True
                continue
            self._body.append(byte)
            if len(self._body) > self.max_payload + 1:
                self._error = "KISS payload exceeds maximum size"
                self._body.clear()
        return frames
