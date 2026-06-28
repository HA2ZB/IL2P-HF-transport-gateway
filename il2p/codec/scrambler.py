from __future__ import annotations

INIT_TX_LFSR = 0x00F
INIT_RX_LFSR = 0x1F0


def scramble_bit(inp: int, state: int) -> tuple[int, int]:
    out = ((state >> 4) ^ state) & 1
    state = (((((inp ^ state) & 1) << 9) | (state ^ ((state & 1) << 4))) >> 1)
    return out, state


def il2p_scramble_block(data: bytes) -> bytes:
    state = INIT_TX_LFSR
    out = bytearray(len(data))
    skipping = True
    ob = 0
    om = 0x80
    for ib, value in enumerate(data):
        for im in (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01):
            inp = 1 if (value & im) else 0
            s, state = scramble_bit(inp, state)
            if ib == 0 and im == 0x04:
                skipping = False
            if not skipping:
                if s:
                    out[ob] |= om
                om >>= 1
                if om == 0:
                    om = 0x80
                    ob += 1
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
