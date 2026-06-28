from __future__ import annotations

from reedsolo import RSCodec, ReedSolomonError


def encode_rs_parity(block: bytes, nsym: int) -> bytes:
    rs = RSCodec(nsym=nsym, nsize=255, fcr=0, prim=0x11D, generator=2)
    return bytes(rs.encode(block)[-nsym:])


def decode_rs_block(block: bytes, nsym: int, label: str = "RS") -> tuple[bytes, int]:
    rs = RSCodec(nsym=nsym, nsize=255, fcr=0, prim=0x11D, generator=2)
    try:
        decoded_msg, _decoded_full, errata_pos = rs.decode(block)
    except ReedSolomonError as e:
        raise ValueError(f"{label} decode failed: {e}") from e
    return bytes(decoded_msg), len(errata_pos)
