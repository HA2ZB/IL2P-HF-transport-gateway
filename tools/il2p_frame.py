#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from il2p.framing import decode_frame_text, encode_frame_text


def main() -> None:
    ap = argparse.ArgumentParser(description="IL2P text framing encode/decode")
    sub = ap.add_subparsers(dest="cmd", required=True)
    enc = sub.add_parser("encode")
    enc.add_argument("input")
    enc.add_argument("--coding", choices=["base32", "base64", "none"], default="base64")
    dec = sub.add_parser("decode")
    dec.add_argument("input")
    dec.add_argument("-o", "--output", default="rx.il2p")
    args = ap.parse_args()

    if args.cmd == "encode":
        print(encode_frame_text(Path(args.input).read_bytes(), coding=args.coding))
    else:
        data = decode_frame_text(Path(args.input).read_text(encoding="utf-8", errors="replace"))
        Path(args.output).write_bytes(data)
        print(f"WROTE: {args.output}")
        print(f"LEN  : {len(data)}")


if __name__ == "__main__":
    main()
