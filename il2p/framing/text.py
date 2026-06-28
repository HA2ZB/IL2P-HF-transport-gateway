from __future__ import annotations

import base64
import binascii
import re
from typing import Literal

BEGIN_TAG = "<IL2P>"
END_TAG = "</IL2P>"
BASE32_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=")
BASE64_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
Coding = Literal["base32", "base64", "none"]


class FramingError(ValueError):
    pass


def base32_len_for_bytes(n: int) -> int:
    return ((n + 4) // 5) * 8


def base64_len_for_bytes(n: int) -> int:
    return ((n + 2) // 3) * 4


def coded_len_for_bytes(n: int, coding: Coding) -> int:
    if coding == "base32":
        return base32_len_for_bytes(n)
    if coding == "base64":
        return base64_len_for_bytes(n)
    if coding == "none":
        return n
    raise FramingError(f"Unsupported coding: {coding}")


def clean_text(s: str) -> str:
    return "".join(s.split())


def encode_frame_text(data: bytes, coding: Coding = "base64", prefix: str = "IL2P", callsign: str | None = None) -> str:
    if coding == "base32":
        coded = base64.b32encode(data).decode("ascii")
    elif coding == "base64":
        coded = base64.b64encode(data).decode("ascii")
    elif coding == "none":
        try:
            coded = data.decode("latin1")
        except UnicodeDecodeError as e:
            raise FramingError("NONE coding needs byte-preserving text path") from e
    else:
        raise FramingError(f"Unsupported coding: {coding}")
    header = f"{prefix} CODING={coding.upper()} LEN={len(data)}"
    if callsign:
        header = f"{callsign.upper()} {header}"
    return f"{header} {BEGIN_TAG}{coded}{END_TAG}"


def _filter_coded(s: str, coding: Coding) -> str:
    if coding == "base32":
        return "".join(ch for ch in s.upper() if ch in BASE32_ALLOWED)
    if coding == "base64":
        return "".join(ch for ch in s if ch in BASE64_ALLOWED)
    return s


def _decode_coded(coded: str, coding: Coding) -> bytes:
    try:
        if coding == "base32":
            return base64.b32decode(_filter_coded(coded, "base32"), casefold=True)
        if coding == "base64":
            return base64.b64decode(_filter_coded(coded, "base64"), validate=False)
        if coding == "none":
            return coded.encode("latin1")
    except (binascii.Error, ValueError) as e:
        raise FramingError(f"{coding} decode failed: {e}") from e
    raise FramingError(f"Unsupported coding: {coding}")


def detect_coding_explicit(header: str) -> Coding | None:
    m = re.search(r"CODING\D{0,12}(BASE32|B32|BASE64|B64|NONE|RAW|32|64)", header, re.IGNORECASE)
    if not m:
        return None
    v = m.group(1).upper()
    if "64" in v:
        return "base64"
    if "32" in v:
        return "base32"
    return "none"


def decode_frame_text(text: str, preferred: Coding | None = None) -> bytes:
    compact = clean_text(text)
    begin = compact.find(BEGIN_TAG)
    if begin < 0:
        raise FramingError("BEGIN tag not found: <IL2P>")
    header = compact[:begin]
    coding = preferred or detect_coding_explicit(header)
    m = re.search(r"LEN=?(\d{1,4})", header, re.IGNORECASE)
    expected_len = int(m.group(1)) if m else None

    body_start = begin + len(BEGIN_TAG)
    end = compact.find(END_TAG, body_start)
    body = compact[body_start:] if end < 0 else compact[body_start:end]

    candidates: list[Coding] = [coding] if coding else ["base64", "base32"]
    last_error: Exception | None = None
    for cand in candidates:
        try:
            if expected_len is not None and end < 0:
                clen = coded_len_for_bytes(expected_len, cand)
                body_try = body[:clen]
            else:
                body_try = body
            data = _decode_coded(body_try, cand)
            if expected_len is not None and len(data) != expected_len:
                raise FramingError(f"Decoded length mismatch: got {len(data)}, expected {expected_len}")
            return data
        except Exception as e:  # keep trying fallback coding
            last_error = e
    raise FramingError(str(last_error) if last_error else "Frame decode failed")


def extract_frame_candidates(text: str) -> list[str]:
    compact = clean_text(text)
    out: list[str] = []
    pos = 0
    while True:
        begin = compact.find(BEGIN_TAG, pos)
        if begin < 0:
            break
        header_start = max(0, compact.rfind("IL2P", 0, begin))
        end = compact.find(END_TAG, begin + len(BEGIN_TAG))
        if end >= 0:
            out.append(compact[header_start:end + len(END_TAG)])
            pos = end + len(END_TAG)
        else:
            out.append(compact[header_start:])
            break
    return out
