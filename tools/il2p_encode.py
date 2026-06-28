#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from il2p.codec import encode_il2p_type1_ui


def hexs(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def main() -> None:
    ap = argparse.ArgumentParser(description="IL2P Type-1 UI/APRS encoder")
    ap.add_argument("src", nargs="?", default="HA2ZB-0")
    ap.add_argument("dst", nargs="?", default="APIL2P-0")
    ap.add_argument("info", nargs="?", default="=4739.97N/01938.97E-IL2P-TEST")
    ap.add_argument("fec", nargs="?", type=int, choices=[0, 1], default=0)
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    ax25, raw_hdr, full_hdr, enc_payload, full_packet = encode_il2p_type1_ui(
        args.src, args.dst, args.info.encode("ascii"), args.fec
    )
    if args.output:
        Path(args.output).write_bytes(full_packet)
        print(f"IL2P binary frame written to: {args.output}")
        print("IL2P_LEN=", len(full_packet))
        return
    print("AX25_ORIGINAL=", hexs(ax25))
    print("IL2P_RAW_HDR=", hexs(raw_hdr))
    print("IL2P_FULL=", hexs(full_packet))


if __name__ == "__main__":
    main()
