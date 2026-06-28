# File: IL2P_fldigi_frame.py

import sys
import re
import base64
import argparse
from pathlib import Path


BEGIN_TAG = "<IL2P>"
END_TAG = "</IL2P>"


def base32_len_for_bytes(n: int) -> int:
    return ((n + 4) // 5) * 8


def clean_text(s: str) -> str:
    s = s.upper()

    s = s.replace("\r", "")
    s = s.replace("\n", "")

    return s


def read_text_auto(path: str) -> str:
    raw = Path(path).read_bytes()

    for enc in ("utf-8", "ascii", "utf-16", "utf-16-le", "cp1250"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass

    return raw.decode("utf-8", errors="ignore")


def encode_file(input_path: str) -> str:
    data = Path(input_path).read_bytes()
    frame_len = len(data)

    b32 = base64.b32encode(data).decode("ascii")

    # New compact, human-readable, marker-light format:
    #
    # IL2P LEN=60 <IL2P>BASE32</IL2P>
    #
    return "".join([
        f"IL2P LEN={frame_len} ",
        BEGIN_TAG,
        b32,
        END_TAG,
        ""
    ])


def filter_base32(s: str) -> str:
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=")
    return "".join(ch for ch in s if ch in allowed)


def try_decode_len_path(text: str) -> bytes:
    clean = clean_text(text)

    # Accept:
    #   LEN=60<IL2P>
    #   LEN60<IL2P>
    #
    m = re.search(r"LEN=?(\d{2,3})<IL2P>", clean)

    if not m:
        raise ValueError("LEN + <IL2P> pattern not found")

    expected_len = int(m.group(1))
    payload_start = m.end()

    b32_len = base32_len_for_bytes(expected_len)
    b32 = clean[payload_start:payload_start + b32_len]

    if len(b32) != b32_len:
        raise ValueError(
            f"Not enough Base32 data: expected {b32_len}, got {len(b32)}"
        )

    data = base64.b32decode(b32, casefold=True)

    if len(data) != expected_len:
        raise ValueError(
            f"Length mismatch: expected {expected_len}, got {len(data)}"
        )

    return data


def try_decode_tag_path(text: str) -> bytes:
    clean = clean_text(text)

    begin = clean.find(BEGIN_TAG)
    if begin < 0:
        raise ValueError("BEGIN tag not found")

    end = clean.find(END_TAG, begin + len(BEGIN_TAG))
    if end < 0:
        raise ValueError("END tag not found")

    raw_payload = clean[begin + len(BEGIN_TAG):end]
    b32 = filter_base32(raw_payload)

    if not b32:
        raise ValueError("Empty Base32 payload")

    data = base64.b32decode(b32, casefold=True)
    return data


def decode_text(text: str) -> bytes:
    # Primary path:
    #   LEN=nn <IL2P> + exact Base32 length
    try:
        return try_decode_len_path(text)
    except Exception as e_len:
        # Fallback:
        #   <IL2P> ... </IL2P>
        try:
            return try_decode_tag_path(text)
        except Exception as e_tag:
            raise ValueError(
                f"Decode failed: LEN path: {e_len}; TAG path: {e_tag}"
            )


def decode_file(input_path: str, output_path: str) -> None:
    text = read_text_auto(input_path)
    data = decode_text(text)
    Path(output_path).write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="IL2P <-> fldigi Contestia-safe Base32 frame converter"
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    enc = sub.add_parser(
        "encode",
        help="Encode IL2P binary to fldigi-safe Base32 text frame"
    )
    enc.add_argument("input", help="Input IL2P binary file")

    dec = sub.add_parser(
        "decode",
        help="Decode received fldigi Base32 text frame to IL2P binary"
    )
    dec.add_argument("input", help="Input received text/log file")
    dec.add_argument(
        "-o",
        "--output",
        default="decoded.il2p",
        help="Output IL2P binary file, default: decoded.il2p"
    )

    args = parser.parse_args()

    try:
        if args.cmd == "encode":
            print(encode_file(args.input), end="")
            return 0

        if args.cmd == "decode":
            decode_file(args.input, args.output)
            print(f"Decoded IL2P written to: {args.output}")
            return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())