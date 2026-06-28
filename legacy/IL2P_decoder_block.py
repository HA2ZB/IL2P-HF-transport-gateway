# IL2P_decoder.py
# pip install reedsolo

from reedsolo import RSCodec, ReedSolomonError

INIT_RX_LFSR = 0x1F0


def hex_to_bytes(s: str) -> bytes:
    return bytes.fromhex(s.replace(",", " ").replace("0x", ""))


def dump_hex(label: str, data: bytes) -> None:
    print(f"{label}= " + " ".join(f"{b:02X}" for b in data))


def descramble_bit(in_bit: int, state: int) -> tuple[int, int]:
    in_bit &= 1
    out_bit = (in_bit ^ state) & 1
    state = ((state >> 1) | (in_bit << 8)) ^ (in_bit << 3)
    return out_bit, state


def il2p_descramble_block(data: bytes) -> bytes:
    state = INIT_RX_LFSR
    out = bytearray(len(data))

    for i, value in enumerate(data):
        out_byte = 0

        for mask in (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01):
            in_bit = 1 if (value & mask) else 0
            out_bit, state = descramble_bit(in_bit, state)

            if out_bit:
                out_byte |= mask

        out[i] = out_byte

    return bytes(out)


def decode_rs_block(block: bytes, nsym: int, label: str = "RS") -> bytes:
    rs = RSCodec(nsym=nsym, nsize=255, fcr=0, prim=0x11D, generator=2)

    try:
        decoded_msg, decoded_full, errata_pos = rs.decode(block)
    except ReedSolomonError as e:
        raise ValueError(f"{label} decode failed: {e}") from e

    print(f"{label}_CORRECTED_SYMBOLS= {len(errata_pos)}")

    return bytes(decoded_msg)


def sixbit_to_ascii(v: int) -> str:
    return chr((v & 0x3F) + 0x20)


def decode_sixbit_callsign(data: bytes) -> str:
    return "".join(sixbit_to_ascii(b) for b in data).rstrip()


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

    blocks = (
        [large_size] * large_count
        + [small_size] * small_count
    )

    return blocks, parity_n


def get_field(hdr: bytes, bit_num: int, lsb_index: int, width: int) -> int:
    result = 0
    idx = lsb_index - width + 1

    while width > 0:
        result <<= 1

        if hdr[idx] & (1 << bit_num):
            result |= 1

        idx += 1
        width -= 1

    return result


def decode_pid(pid4: int) -> int:
    table = [
        0xF0, 0xF0, 0x20, 0x01,
        0x06, 0x07, 0x08, 0xF0,
        0xF0, 0xF0, 0xF0, 0xCC,
        0xCD, 0xCE, 0xCF, 0xF0,
    ]
    return table[pid4 & 0x0F]


def parse_il2p_header(raw: bytes) -> dict:
    if len(raw) != 13:
        raise ValueError(f"Raw IL2P header must be 13 bytes, got {len(raw)}")

    dst = decode_sixbit_callsign(raw[0:6])
    src = decode_sixbit_callsign(raw[6:12])

    dst_ssid = (raw[12] >> 4) & 0x0F
    src_ssid = raw[12] & 0x0F

    ui = get_field(raw, 6, 0, 1)
    pid4 = get_field(raw, 6, 4, 4)
    control7 = get_field(raw, 6, 11, 7)

    fec_level = get_field(raw, 7, 0, 1)
    hdr_type = get_field(raw, 7, 1, 1)
    payload_len = get_field(raw, 7, 11, 10)

    ax25_pid = decode_pid(pid4)

    return {
        "dst": dst,
        "src": src,
        "dst_ssid": dst_ssid,
        "src_ssid": src_ssid,
        "ui": ui,
        "pid4": pid4,
        "ax25_pid": ax25_pid,
        "control7": control7,
        "fec_level": fec_level,
        "hdr_type": hdr_type,
        "payload_len": payload_len,
        "is_type1": hdr_type == 1,
        "is_ui": ui == 1 and ((control7 >> 3) & 0x07) == 5,
        "is_no_layer3": ax25_pid == 0xF0,
    }


def decode_il2p_payload(payload_encoded: bytes, payload_len: int, fec_level: int) -> bytes:
    blocks, parity_n = split_payload_blocks(payload_len, fec_level)

    payload_parts = []
    offset = 0

    for data_len in blocks:
        block_len = data_len + parity_n
        block = payload_encoded[offset:offset + block_len]

        if len(block) != block_len:
            raise ValueError("Truncated IL2P payload block")

        scrambled_part = decode_rs_block(block, nsym=parity_n, label="PAYLOAD_RS")
        part = il2p_descramble_block(scrambled_part)
        payload_parts.append(part)

        offset += block_len

    if offset != len(payload_encoded):
        raise ValueError(
            f"Extra bytes after payload blocks: {len(payload_encoded) - offset}"
        )

    payload = b"".join(payload_parts)

    if len(payload) != payload_len:
        raise ValueError(
            f"Decoded payload length mismatch: got {len(payload)}, expected {payload_len}"
        )

    return payload


def decode_il2p_frame(frame: bytes | str) -> dict:
    if isinstance(frame, str):
        frame = hex_to_bytes(frame)

    if len(frame) < 17:
        raise ValueError("IL2P frame too short")

    header_15 = frame[:15]

    scrambled_header = decode_rs_block(header_15, nsym=2, label="HEADER_RS")
    raw_header = il2p_descramble_block(scrambled_header)
    header = parse_il2p_header(raw_header)

    if not header["is_type1"]:
        raise NotImplementedError("Most még csak Type1 IL2P header támogatott")

    payload_len = header["payload_len"]
    fec_level = header["fec_level"]

    payload_encoded = frame[15:]
    payload = decode_il2p_payload(payload_encoded, payload_len, fec_level)

    try:
        aprs_text = payload.decode("ascii")
    except UnicodeDecodeError:
        aprs_text = payload.decode("ascii", errors="replace")

    return {
        "src": header["src"],
        "src_ssid": header["src_ssid"],
        "dst": header["dst"],
        "dst_ssid": header["dst_ssid"],
        "pid": header["ax25_pid"],
        "payload_len": payload_len,
        "fec_level": fec_level,
        "header_raw": raw_header,
        "header_scrambled": scrambled_header,
        "payload_raw": payload,
        "aprs_text": aprs_text,
        "header": header,
    }


def print_decoded(result: dict) -> None:
    print("IL2P DECODED")
    print(f"  SRC: {result['src']}-{result['src_ssid']}")
    print(f"  DST: {result['dst']}-{result['dst_ssid']}")
    print(f"  PID: 0x{result['pid']:02X}")
    print(f"  FEC: {result['fec_level']}")
    print(f"  LEN: {result['payload_len']}")
    print(f"  APRS: {result['aprs_text']}")


def encode_ax25_addr(callsign: str, ssid: int, last: bool) -> bytes:
    call = callsign.upper().ljust(6)[:6]
    out = bytearray()

    for ch in call:
        out.append(ord(ch) << 1)

    ssid_byte = 0x60 | ((ssid & 0x0F) << 1)

    if last:
        ssid_byte |= 0x01

    out.append(ssid_byte)
    return bytes(out)


def rebuild_ax25_ui_frame(decoded: dict) -> bytes:
    dst = encode_ax25_addr(decoded["dst"], decoded["dst_ssid"], last=False)
    src = encode_ax25_addr(decoded["src"], decoded["src_ssid"], last=True)

    control = bytes([0x03])
    pid = bytes([decoded["pid"]])
    info = decoded["payload_raw"]

    return dst + src + control + pid + info


def print_ax25_frame(ax25: bytes) -> None:
    dump_hex("AX25_REBUILT", ax25)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python IL2P_decoder_block.py rx.il2p")
        print("  python IL2P_decoder_block.py \"68 C8 85 ...\"")
        raise SystemExit(1)

    arg = sys.argv[1]

    p = Path(arg)

    if p.exists():
        il2p_full = p.read_bytes()
    else:
        il2p_full = arg

    decoded = decode_il2p_frame(il2p_full)

    dump_hex("HEADER_RAW", decoded["header_raw"])
    dump_hex("PAYLOAD_RAW", decoded["payload_raw"])
    print_decoded(decoded)

    ax25 = rebuild_ax25_ui_frame(decoded)
    print_ax25_frame(ax25)