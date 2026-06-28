#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from il2p.codec.il2p_type1 import decode_il2p_frame_object, rebuild_ax25_ui_frame


def hexs(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def main() -> None:
    ap = argparse.ArgumentParser(description="IL2P Type-1 UI/APRS decoder")
    ap.add_argument("input", help="Binary file or hex string")
    args = ap.parse_args()
    p = Path(args.input)
    frame = p.read_bytes() if p.exists() else args.input
    decoded = decode_il2p_frame_object(frame)
    print("HEADER_RAW=", hexs(decoded.header_raw))
    print("PAYLOAD_RAW=", hexs(decoded.payload_raw))
    print("IL2P DECODED")
    print(f"  SRC: {decoded.src}-{decoded.src_ssid}")
    print(f"  DST: {decoded.dst}-{decoded.dst_ssid}")
    print(f"  PID: 0x{decoded.pid:02X}")
    print(f"  FEC: {decoded.fec_level}")
    print(f"  LEN: {decoded.payload_len}")
    print(f"  APRS: {decoded.aprs_text}")
    print(f"HEADER_RS_CORRECTED_SYMBOLS= {decoded.rs.header_corrected_symbols}")
    print(f"PAYLOAD_RS_CORRECTED_SYMBOLS= {decoded.rs.payload_corrected_symbols}")
    print("AX25_REBUILT=", hexs(rebuild_ax25_ui_frame(decoded)))


if __name__ == "__main__":
    main()
