from __future__ import annotations


def parse_callsign(s: str) -> tuple[str, int]:
    s = s.upper().strip()
    if "-" in s:
        call, ssid_text = s.split("-", 1)
        ssid = int(ssid_text)
    else:
        call, ssid = s, 0
    if not (0 <= ssid <= 15):
        raise ValueError(f"SSID out of range: {ssid}")
    return call, ssid


def encode_ax25_addr(callsign: str, ssid: int, last: bool) -> bytes:
    call = callsign.upper().ljust(6)[:6]
    out = bytearray(ord(ch) << 1 for ch in call)
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
    if last:
        ssid_byte |= 0x01
    out.append(ssid_byte)
    return bytes(out)


def build_ax25_ui_frame(src_full: str, dst_full: str, info: bytes) -> bytes:
    dst, dst_ssid = parse_callsign(dst_full)
    src, src_ssid = parse_callsign(src_full)
    return (
        encode_ax25_addr(dst, dst_ssid, last=False)
        + encode_ax25_addr(src, src_ssid, last=True)
        + b"\x03\xF0"
        + info
    )
