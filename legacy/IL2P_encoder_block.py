# File: IL2P_encoder_block.py
#
# Usage:
#
#   python IL2P_encoder_block.py
#
#   python IL2P_encoder_block.py HA2ZB-0 APIL2P-0 "=4739.97N/01938.97E-IL2P-TEST" 0
#
#   python IL2P_encoder_block.py HA2ZB-0 APIL2P-0 "HELLO WORLD" 1
#
#   python IL2P_encoder_block.py HA2ZB-0 APIL2P-0 "=4739.97N/01938.97E-IL2P-TEST" 0 -o test.il2p
#

import argparse
from reedsolo import RSCodec


# ============================================================
# Helpers
# ============================================================

def hexs(data):
    return " ".join(f"{b:02X}" for b in data)


def parse_callsign(s):
    s = s.upper()

    if "-" in s:
        call, ssid = s.split("-")
        ssid = int(ssid)
    else:
        call = s
        ssid = 0

    return call, ssid


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


def build_ax25_ui_frame(src_full, dst_full, info: bytes) -> bytes:
    dst, dst_ssid = parse_callsign(dst_full)
    src, src_ssid = parse_callsign(src_full)

    dst_addr = encode_ax25_addr(dst, dst_ssid, last=False)
    src_addr = encode_ax25_addr(src, src_ssid, last=True)

    return (
        dst_addr +
        src_addr +
        bytes([0x03]) +
        bytes([0xF0]) +
        info
    )


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


# ============================================================
# IL2P scramble, Direwolf compatible
# ============================================================

INIT_TX_LFSR = 0x00F


def scramble_bit(inp, state):
    out = ((state >> 4) ^ state) & 1

    state = (
        (
            (((inp ^ state) & 1) << 9)
            | (state ^ ((state & 1) << 4))
        ) >> 1
    )

    return out, state


def il2p_scramble_block(data: bytes) -> bytes:
    state = INIT_TX_LFSR

    out = bytearray(len(data))

    skipping = True

    ob = 0
    om = 0x80

    for ib in range(len(data)):
        for im in [0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01]:
            inp = 1 if (data[ib] & im) else 0

            s, state = scramble_bit(inp, state)

            # discard first 5 bits
            if ib == 0 and im == 0x04:
                skipping = False

            if not skipping:
                if s:
                    out[ob] |= om

                om >>= 1

                if om == 0:
                    om = 0x80
                    ob += 1

    # flush 5 bits
    x = state

    for _ in range(5):
        s, x = scramble_bit(0, x)

        if s:
            out[ob] |= om

        om >>= 1

        if om == 0:
            om = 0x80
            ob += 1

    return bytes(out)


# ============================================================
# IL2P header helpers
# ============================================================

hdr = bytearray(13)


def set_field(bit_num, lsb_index, width, value):
    global hdr

    while width > 0 and value != 0:
        if value & 1:
            hdr[lsb_index] |= (1 << bit_num)

        value >>= 1
        lsb_index -= 1
        width -= 1


def ascii_to_sixbit(c):
    return ord(c) - ord(" ")


def encode_callsign_6(call):
    call = call.ljust(6)

    return [ascii_to_sixbit(c) for c in call]


# ============================================================
# Build IL2P type-1 UI/APRS header
# ============================================================

def make_il2p_header(dst_full, src_full, payload_len, max_fec=0):
    global hdr

    hdr = bytearray(13)

    dst, dst_ssid = parse_callsign(dst_full)
    src, src_ssid = parse_callsign(src_full)

    # bytes 0..5
    hdr[0:6] = bytes(encode_callsign_6(dst[:6]))

    # bytes 6..11
    hdr[6:12] = bytes(encode_callsign_6(src[:6]))

    # SSIDs
    hdr[12] = (dst_ssid << 4) | src_ssid

    # UI flag
    set_field(6, 0, 1, 1)

    # PID = 0xF0 -> encoded as 15
    set_field(6, 4, 4, 15)

    # CONTROL:
    # UI opcode = 5
    # command bit = 1
    set_field(6, 11, 7, (5 << 3) | (1 << 2))

    # FEC LEVEL
    set_field(7, 0, 1, 1 if max_fec else 0)

    # HEADER TYPE = 1
    set_field(7, 1, 1, 1)

    # PAYLOAD BYTE COUNT
    set_field(7, 11, 10, payload_len)

    return bytes(hdr)


# ============================================================
# Full encoder
# ============================================================

def encode_il2p_type1_ui(src, dst, info: bytes, max_fec=0):
    ax25_frame = build_ax25_ui_frame(src, dst, info)

    raw_hdr = make_il2p_header(dst, src, len(info), max_fec)

    scr_hdr = il2p_scramble_block(raw_hdr)

    hdr_rsc = RSCodec(
        nsym=2,
        nsize=255,
        fcr=0,
        prim=0x11D,
        generator=2
    )

    hdr_block = bytes(255 - len(scr_hdr) - 2) + scr_hdr

    hdr_parity = hdr_rsc.encode(hdr_block)[-2:]

    full_hdr = scr_hdr + hdr_parity

    blocks, parity_n = split_payload_blocks(len(info), max_fec)

    payload_rsc = RSCodec(
        nsym=parity_n,
        nsize=255,
        fcr=0,
        prim=0x11D,
        generator=2
    )

    encoded_blocks = []
    offset = 0

    for data_len in blocks:
        part = info[offset:offset + data_len]

        scr_part = il2p_scramble_block(part)

        payload_block = (
            bytes(255 - data_len - parity_n)
            + scr_part
        )

        parity = payload_rsc.encode(payload_block)[-parity_n:]

        encoded_blocks.append(scr_part + parity)

        offset += data_len

    encoded_payload = b"".join(encoded_blocks)

    full_packet = full_hdr + encoded_payload

    return (
        ax25_frame,
        raw_hdr,
        full_hdr,
        encoded_payload,
        full_packet
    )


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Direwolf-compatible IL2P Type-1 UI/APRS encoder"
    )

    parser.add_argument(
        "src",
        nargs="?",
        default="HA2ZB-0",
        help="Source callsign, default: HA2ZB-0"
    )

    parser.add_argument(
        "dst",
        nargs="?",
        default="APIL2P-0",
        help="Destination callsign, default: APIL2P-0"
    )

    parser.add_argument(
        "info",
        nargs="?",
        default="=4739.97N/01938.97E-IL2P-TEST",
        help="APRS information field / payload"
    )

    parser.add_argument(
        "fec",
        nargs="?",
        type=int,
        default=0,
        choices=[0, 1],
        help="FEC level: 0 or 1, default: 0"
    )

    parser.add_argument(
        "-o",
        "--output",
        help="Write raw IL2P binary frame to file"
    )

    args = parser.parse_args()

    info = args.info.encode("ascii")

    ax25_frame, raw_hdr, full_hdr, enc_payload, full_packet = encode_il2p_type1_ui(
        args.src,
        args.dst,
        info,
        args.fec
    )

    if args.output:
        with open(args.output, "wb") as f:
            f.write(full_packet)

        print(f"IL2P binary frame written to: {args.output}")
        print("IL2P_LEN=", len(full_packet))
        return

    print("AX25_ORIGINAL=", hexs(ax25_frame))
    print("IL2P_RAW_HDR=", hexs(raw_hdr))
    print("IL2P_SCR_HDR=", hexs(full_hdr))
    print("IL2P_PAYLOAD=", hexs(enc_payload))
    print("IL2P_FULL=", hexs(full_packet))
    print("IL2P_LEN=", len(full_packet))


if __name__ == "__main__":
    main()