from __future__ import annotations

from .ax25 import build_ax25_ui_frame, encode_ax25_addr, parse_callsign
from .models import DecodedIL2PFrame, EncodedIL2PFrame, RSStats
from .rs import decode_rs_block, encode_rs_parity
from .scrambler import il2p_descramble_block, il2p_scramble_block


def hex_to_bytes(s: str) -> bytes:
    return bytes.fromhex(s.replace(",", " ").replace("0x", ""))


def split_payload_blocks(payload_len: int, fec_level: int) -> tuple[list[int], int]:
    if payload_len <= 0:
        return [], 0
    if fec_level:
        block_count = (payload_len + 238) // 239
        parity_n = 16
    else:
        block_count = (payload_len + 246) // 247
        small_size_tmp = payload_len // block_count
        if small_size_tmp <= 61:
            parity_n = 2
        elif small_size_tmp <= 123:
            parity_n = 4
        elif small_size_tmp <= 185:
            parity_n = 6
        else:
            parity_n = 8
    small_size = payload_len // block_count
    large_size = small_size + 1
    large_count = payload_len - (block_count * small_size)
    small_count = block_count - large_count
    return [large_size] * large_count + [small_size] * small_count, parity_n


def _set_field(hdr: bytearray, bit_num: int, lsb_index: int, width: int, value: int) -> None:
    while width > 0 and value != 0:
        if value & 1:
            hdr[lsb_index] |= 1 << bit_num
        value >>= 1
        lsb_index -= 1
        width -= 1


def _get_field(hdr: bytes, bit_num: int, lsb_index: int, width: int) -> int:
    result = 0
    idx = lsb_index - width + 1
    while width > 0:
        result <<= 1
        if hdr[idx] & (1 << bit_num):
            result |= 1
        idx += 1
        width -= 1
    return result


def _ascii_to_sixbit(c: str) -> int:
    return ord(c) - ord(" ")


def _sixbit_to_ascii(v: int) -> str:
    return chr((v & 0x3F) + 0x20)


def _encode_callsign_6(call: str) -> list[int]:
    return [_ascii_to_sixbit(c) for c in call.ljust(6)]


def _decode_sixbit_callsign(data: bytes) -> str:
    return "".join(_sixbit_to_ascii(b) for b in data).rstrip()


def make_il2p_header(dst_full: str, src_full: str, payload_len: int, max_fec: int = 0) -> bytes:
    hdr = bytearray(13)
    dst, dst_ssid = parse_callsign(dst_full)
    src, src_ssid = parse_callsign(src_full)
    hdr[0:6] = bytes(_encode_callsign_6(dst[:6]))
    hdr[6:12] = bytes(_encode_callsign_6(src[:6]))
    hdr[12] = (dst_ssid << 4) | src_ssid
    _set_field(hdr, 6, 0, 1, 1)              # UI flag
    _set_field(hdr, 6, 4, 4, 15)             # PID 0xF0 encoded as 15
    _set_field(hdr, 6, 11, 7, (5 << 3) | (1 << 2))
    _set_field(hdr, 7, 0, 1, 1 if max_fec else 0)
    _set_field(hdr, 7, 1, 1, 1)              # Type 1
    _set_field(hdr, 7, 11, 10, payload_len)
    return bytes(hdr)


def encode_il2p_type1_ui_frame(src: str, dst: str, info: bytes, max_fec: int = 0) -> EncodedIL2PFrame:
    ax25_frame = build_ax25_ui_frame(src, dst, info)
    raw_hdr = make_il2p_header(dst, src, len(info), max_fec)
    scr_hdr = il2p_scramble_block(raw_hdr)
    hdr_block = bytes(255 - len(scr_hdr) - 2) + scr_hdr
    full_hdr = scr_hdr + encode_rs_parity(hdr_block, nsym=2)

    blocks, parity_n = split_payload_blocks(len(info), max_fec)
    encoded_blocks: list[bytes] = []
    offset = 0
    for data_len in blocks:
        part = info[offset:offset + data_len]
        scr_part = il2p_scramble_block(part)
        payload_block = bytes(255 - data_len - parity_n) + scr_part
        encoded_blocks.append(scr_part + encode_rs_parity(payload_block, nsym=parity_n))
        offset += data_len
    encoded_payload = b"".join(encoded_blocks)
    return EncodedIL2PFrame(ax25_frame, raw_hdr, full_hdr, encoded_payload, full_hdr + encoded_payload)


def encode_il2p_type1_ui(src: str, dst: str, info: bytes, max_fec: int = 0) -> tuple[bytes, bytes, bytes, bytes, bytes]:
    """Legacy-compatible encoder API."""
    return encode_il2p_type1_ui_frame(src, dst, info, max_fec).as_legacy_tuple()


def _decode_pid(pid4: int) -> int:
    table = [0xF0, 0xF0, 0x20, 0x01, 0x06, 0x07, 0x08, 0xF0, 0xF0, 0xF0, 0xF0, 0xCC, 0xCD, 0xCE, 0xCF, 0xF0]
    return table[pid4 & 0x0F]


def parse_il2p_header(raw: bytes) -> dict:
    if len(raw) != 13:
        raise ValueError(f"Raw IL2P header must be 13 bytes, got {len(raw)}")
    dst = _decode_sixbit_callsign(raw[0:6])
    src = _decode_sixbit_callsign(raw[6:12])
    dst_ssid = (raw[12] >> 4) & 0x0F
    src_ssid = raw[12] & 0x0F
    ui = _get_field(raw, 6, 0, 1)
    pid4 = _get_field(raw, 6, 4, 4)
    control7 = _get_field(raw, 6, 11, 7)
    fec_level = _get_field(raw, 7, 0, 1)
    hdr_type = _get_field(raw, 7, 1, 1)
    payload_len = _get_field(raw, 7, 11, 10)
    ax25_pid = _decode_pid(pid4)
    return {
        "dst": dst, "src": src, "dst_ssid": dst_ssid, "src_ssid": src_ssid,
        "ui": ui, "pid4": pid4, "ax25_pid": ax25_pid, "control7": control7,
        "fec_level": fec_level, "hdr_type": hdr_type, "payload_len": payload_len,
        "is_type1": hdr_type == 1,
        "is_ui": ui == 1 and ((control7 >> 3) & 0x07) == 5,
        "is_no_layer3": ax25_pid == 0xF0,
    }


def decode_il2p_payload(payload_encoded: bytes, payload_len: int, fec_level: int) -> tuple[bytes, list[int]]:
    blocks, parity_n = split_payload_blocks(payload_len, fec_level)
    payload_parts: list[bytes] = []
    corrected: list[int] = []
    offset = 0
    for data_len in blocks:
        block_len = data_len + parity_n
        block = payload_encoded[offset:offset + block_len]
        if len(block) != block_len:
            raise ValueError("Truncated IL2P payload block")
        scrambled_part, nfix = decode_rs_block(block, nsym=parity_n, label="PAYLOAD_RS")
        corrected.append(nfix)
        payload_parts.append(il2p_descramble_block(scrambled_part))
        offset += block_len
    if offset != len(payload_encoded):
        raise ValueError(f"Extra bytes after payload blocks: {len(payload_encoded) - offset}")
    payload = b"".join(payload_parts)
    if len(payload) != payload_len:
        raise ValueError(f"Decoded payload length mismatch: got {len(payload)}, expected {payload_len}")
    return payload, corrected


def decode_il2p_frame_object(frame: bytes | str) -> DecodedIL2PFrame:
    if isinstance(frame, str):
        frame = hex_to_bytes(frame)
    if len(frame) < 17:
        raise ValueError("IL2P frame too short")
    header_15 = frame[:15]
    scrambled_header, header_fix = decode_rs_block(header_15, nsym=2, label="HEADER_RS")
    raw_header = il2p_descramble_block(scrambled_header)
    header = parse_il2p_header(raw_header)
    if not header["is_type1"]:
        raise NotImplementedError("Most még csak Type1 IL2P header támogatott")
    payload, payload_fix = decode_il2p_payload(frame[15:], header["payload_len"], header["fec_level"])
    try:
        aprs_text = payload.decode("ascii")
    except UnicodeDecodeError:
        aprs_text = payload.decode("ascii", errors="replace")
    return DecodedIL2PFrame(
        src=header["src"], src_ssid=header["src_ssid"], dst=header["dst"], dst_ssid=header["dst_ssid"],
        pid=header["ax25_pid"], payload_len=header["payload_len"], fec_level=header["fec_level"],
        header_raw=raw_header, header_scrambled=scrambled_header, payload_raw=payload, aprs_text=aprs_text, header=header,
        rs=RSStats(header_corrected_symbols=header_fix, payload_corrected_symbols=sum(payload_fix), payload_block_corrected_symbols=payload_fix),
    )


def decode_il2p_frame(frame: bytes | str) -> dict:
    """Legacy-compatible decoder API."""
    return decode_il2p_frame_object(frame).as_legacy_dict()


def rebuild_ax25_ui_frame(decoded: dict | DecodedIL2PFrame) -> bytes:
    if isinstance(decoded, DecodedIL2PFrame):
        dst, dst_ssid, src, src_ssid, pid, payload = decoded.dst, decoded.dst_ssid, decoded.src, decoded.src_ssid, decoded.pid, decoded.payload_raw
    else:
        dst, dst_ssid, src, src_ssid, pid, payload = decoded["dst"], decoded["dst_ssid"], decoded["src"], decoded["src_ssid"], decoded["pid"], decoded["payload_raw"]
    return encode_ax25_addr(dst, dst_ssid, last=False) + encode_ax25_addr(src, src_ssid, last=True) + bytes([0x03, pid]) + payload
