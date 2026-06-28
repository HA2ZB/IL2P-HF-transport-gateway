# File: IL2P_fldigi_rxwatch.py

import re
import sys
import time
import base64
import argparse
import subprocess
import xmlrpc.client
from pathlib import Path


FLDIGI_URL = "http://127.0.0.1:7362"

BEGIN_TAG = "<IL2P>"
END_TAG = "</IL2P>"

BASE32_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=")
BASE64_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")


def connect():
    return xmlrpc.client.ServerProxy(FLDIGI_URL)


def clean_text(s: str) -> str:
    return "".join(s.split()).upper()


def base32_len_for_bytes(n: int) -> int:
    return ((n + 4) // 5) * 8




def base64_len_for_bytes(n: int) -> int:
    return ((n + 2) // 3) * 4


def detect_coding_explicit(clean: str) -> str | None:
    """Return explicit/recognizable coding from header, or None if unknown.

    Normal:
        HA2ZB IL2P CODING=BASE64 LEN=58 <IL2P>...

    Damaged/truncated:
        =64 <IL2P>...
    """
    begin = clean.find(BEGIN_TAG)
    header = clean[:begin] if begin >= 0 else clean

    m = re.search(r"CODING\D{0,12}(BASE32|B32|BASE64|B64|32|64)", header, re.IGNORECASE)
    if m:
        v = m.group(1).upper()
        return "base64" if "64" in v else "base32"

    # Damaged/truncated header tail, e.g. '=64 <IL2P>'.
    if re.search(r"(?:=|G)64$", header, re.IGNORECASE):
        return "base64"
    if re.search(r"(?:=|G)32$", header, re.IGNORECASE):
        return "base32"

    return None


def detect_coding_candidates(clean: str) -> list[str]:
    """Return coding candidates.

    If the self-describing CODING= field is intact or recognizably damaged,
    return that single coding.  If it is missing, try both likely text codings.
    Base64 is tried first because it is less restrictive and is used by Olivia
    tests; the IL2P decoder still validates the resulting binary candidate.
    """
    explicit = detect_coding_explicit(clean)
    if explicit:
        return [explicit]

    return ["base64", "base32"]


def detect_coding(clean: str) -> str:
    """Compatibility helper: return the first coding candidate."""
    return detect_coding_candidates(clean)[0]

def coded_len_for_bytes(n: int, coding: str) -> int:
    if coding == "base64":
        return base64_len_for_bytes(n)
    return base32_len_for_bytes(n)

def parse_snr_db(status: str):
    m = re.search(
        r"s/n:\s*([-+]?\d+(?:\.\d+)?)\s*dB",
        str(status),
        re.IGNORECASE
    )
    if not m:
        return None
    return float(m.group(1))


def filter_base32(s: str) -> str:
    return "".join(ch for ch in s if ch in BASE32_ALLOWED)
    

def filter_base32_strict(s: str) -> str:
    # Csak az eredetileg is nagybetűs Base32 karaktereket fogadja el.
    # A kisbetűs zajt nem alakítja át nagybetűssé.
    return "".join(ch for ch in s if ch in BASE32_ALLOWED)


def collect_base32_from_tail(tail: str, wanted_len: int) -> str:
    out = []

    for ch in tail:
        # Ne uppercaselt szövegből dolgozzon.
        # Csak eredetileg nagybetűs A-Z, 2-7, = mehet át.
        if ch in BASE32_ALLOWED:
            out.append(ch)

        if len(out) >= wanted_len:
            break

    return "".join(out)




def filter_base64_strict(s: str) -> str:
    return "".join(ch for ch in s if ch in BASE64_ALLOWED)


def collect_base64_from_tail(tail: str, wanted_len: int) -> str:
    out = []

    for ch in tail:
        if ch in BASE64_ALLOWED:
            out.append(ch)

        if len(out) >= wanted_len:
            break

    return "".join(out)


def collect_coded_from_tail(tail: str, wanted_len: int, coding: str) -> str:
    if coding == "base64":
        return collect_base64_from_tail(tail, wanted_len)
    return collect_base32_from_tail(tail, wanted_len)


def decode_coded_len_checked(payload: str, expected_len: int, coding: str) -> bytes:
    coded_len = coded_len_for_bytes(expected_len, coding)

    if len(payload) != coded_len:
        raise ValueError(
            f"Not enough {coding.upper()} data: expected {coded_len}, got {len(payload)}"
        )

    if coding == "base64":
        data = base64.b64decode(payload, validate=False)
    else:
        data = base64.b32decode(payload, casefold=True)

    if len(data) != expected_len:
        raise ValueError(
            f"Length mismatch: expected {expected_len}, got {len(data)}"
        )

    return data


def frame_debug_summary(rx_buffer: str) -> str:
    """Return a compact diagnostic summary for a malformed frame candidate."""
    raw = "".join(rx_buffer.split())
    clean = raw.upper()
    coding = detect_coding(clean)

    parts = [f"coding={coding.upper()}"]

    m_len = re.search(r"LEN\D{0,8}(\d{1,4})", clean)
    expected_len = int(m_len.group(1)) if m_len else None
    if expected_len is None:
        parts.append("LEN=missing")
    else:
        parts.append(f"LEN={expected_len}")
        parts.append(f"expected_coded_len={coded_len_for_bytes(expected_len, coding)}")

    begin = clean.find(BEGIN_TAG)
    end = clean.find(END_TAG, begin + len(BEGIN_TAG)) if begin >= 0 else -1
    parts.append(f"begin_tag={'yes' if begin >= 0 else 'no'}")
    parts.append(f"end_tag={'yes' if end >= 0 else 'no'}")

    if begin >= 0:
        start = begin + len(BEGIN_TAG)
        payload_region = raw[start:end] if end >= 0 else raw[start:]
        if coding == "base64":
            filtered = filter_base64_strict(payload_region)
            parts.append(f"filtered_BASE64_len={len(filtered)}")
            parts.append(f"filtered_BASE64_mod4={len(filtered) % 4}")
            try:
                data = base64.b64decode(filtered, validate=False)
                parts.append(f"binary_len={len(data)}")
            except Exception as e:
                parts.append(f"base64_error={e}")
        else:
            filtered = filter_base32_strict(payload_region)
            parts.append(f"filtered_BASE32_len={len(filtered)}")
            parts.append(f"filtered_BASE32_mod8={len(filtered) % 8}")
            try:
                data = base64.b32decode(filtered, casefold=True)
                parts.append(f"binary_len={len(data)}")
            except Exception as e:
                parts.append(f"base32_error={e}")

    return "; ".join(parts)



def frame_candidate_incomplete(rx_buffer: str) -> bool:
    """Return True while a frame is still arriving and should not be reported as rejected.

    We only print diagnostics after the closing tag is present, or after enough
    coded payload characters have arrived to reconstruct the declared LEN.
    This prevents noisy per-character/per-chunk reject messages while fldigi is
    still receiving a long frame.
    """
    raw = "".join(rx_buffer.split())
    clean = raw.upper()
    coding = detect_coding(clean)

    m_len = re.search(r"LEN\D{0,8}(\d{1,4})", clean)
    begin = clean.find(BEGIN_TAG)

    if not m_len or begin < 0:
        return True

    expected_len = int(m_len.group(1))
    expected_coded_len = coded_len_for_bytes(expected_len, coding)

    start = begin + len(BEGIN_TAG)
    end = clean.find(END_TAG, start)

    payload_region = raw[start:end] if end >= 0 else raw[start:]

    if coding == "base64":
        filtered_len = len(filter_base64_strict(payload_region))
    else:
        filtered_len = len(filter_base32_strict(payload_region))

    if end >= 0:
        return False

    if filtered_len >= expected_coded_len:
        return False

    return True


def decode_b32_len_checked(b32: str, expected_len: int) -> bytes:
    b32_len = base32_len_for_bytes(expected_len)

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


def try_decode_len_path(clean: str) -> bytes:
    # Normal path:
    #
    #   LEN=60 <IL2P> BASE32...
    #
    # Tolerates junk between LEN, number and <IL2P>.
    m = re.search(r"LEN\D{0,6}(\d{2,3})\D{0,16}<IL2P>", clean)

    if not m:
        raise ValueError("LEN + <IL2P> pattern not found")

    expected_len = int(m.group(1))
    payload_start = m.end()
    b32_len = base32_len_for_bytes(expected_len)

    tail = clean[payload_start:]

    # If a clean closing tag starts later, do not let its characters pollute payload.
    close_pos = tail.find("<")
    if close_pos >= 0:
        payload_region = tail[:close_pos]
    else:
        payload_region = tail

    b32 = collect_base32_from_tail(payload_region, b32_len)

    # If closing tag was damaged and payload_region was too short, fall back to tail.
    if len(b32) < b32_len:
        b32 = collect_base32_from_tail(tail, b32_len)

    return decode_b32_len_checked(b32, expected_len)


def try_decode_tag_path(clean: str) -> bytes:
    # Fallback:
    #
    #   <IL2P> BASE32 </IL2P>
    #
    begin = clean.find(BEGIN_TAG)

    while begin >= 0:
        end = clean.find(END_TAG, begin + len(BEGIN_TAG))

        if end < 0:
            raise ValueError("END tag not found")

        raw_payload = clean[begin + len(BEGIN_TAG):end]
        b32 = filter_base32(raw_payload)

        if len(b32) % 8 != 0:
            raise ValueError(
                f"Filtered Base32 length is not multiple of 8: {len(b32)}"
            )

        if b32:
            try:
                return base64.b32decode(b32, casefold=True)
            except Exception:
                pass

        begin = clean.find(BEGIN_TAG, begin + 1)

    raise ValueError("No decodable <IL2P>...</IL2P> payload found")


def try_decode_len_recovery_path(clean: str) -> bytes:
    # Desperate recovery:
    #
    # If LEN is clear but <IL2P> is damaged, try to locate the payload start
    # after a nearby '<' or '>' character, or after a long Base32-looking run.
    #
    # Example:
    #   LEN=60 <I,s2P>4AAG7IM3...
    #
    m = re.search(r"LEN\D{0,8}(\d{2,3})", clean)

    if not m:
        raise ValueError("LEN recovery pattern not found")

    expected_len = int(m.group(1))
    b32_len = base32_len_for_bytes(expected_len)

    search_area = clean[m.end():]

    candidate_starts = []

    # Prefer after '>' because in damaged tags like <I,s2P>
    # the payload normally starts after the closing angle bracket.
    p = search_area.find(">")
    if p >= 0:
        candidate_starts.append(p + 1)

    # Then try first long Base32-looking run.
    run = re.search(r"[ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=]{8,}", search_area)
    if run:
        candidate_starts.append(run.start())

    # Last resort: after '<'
    p = search_area.find("<")
    if p >= 0:
        candidate_starts.append(p + 1)

    if not candidate_starts:
        raise ValueError("No recovery payload start candidate found")

    seen = set()

    for start in candidate_starts:
        if start in seen:
            continue
        seen.add(start)

        tail = search_area[start:]
        b32 = collect_base32_from_tail(tail, b32_len)

        try:
            return decode_b32_len_checked(b32, expected_len)
        except Exception:
            pass

    raise ValueError("LEN recovery failed")

def try_extract_il2p_candidates(rx_buffer: str) -> list[bytes]:
    raw = "".join(rx_buffer.split())
    clean = raw.upper()

    candidates = []

    for coding in detect_coding_candidates(clean):
        # A) normál LEN + <IL2P>
        try:
            candidates.append(try_decode_len_path_mixed(raw, clean, coding))
        except Exception:
            pass

        # B) tag fallback
        try:
            candidates.append(try_decode_tag_path_mixed(raw, clean, coding))
        except Exception:
            pass

        # C) recovery: több offset
        candidates.extend(try_decode_len_recovery_candidates_mixed(raw, clean, coding))

    # duplikátumok kiszedése
    uniq = []
    seen = set()

    for c in candidates:
        if c not in seen:
            uniq.append(c)
            seen.add(c)

    return uniq

def strip_whitespace_only(s: str) -> str:
    return "".join(s.split())


def try_extract_il2p_binary(rx_buffer: str) -> bytes:
    raw = strip_whitespace_only(rx_buffer)
    clean = raw.upper()

    last_error = None

    for coding in detect_coding_candidates(clean):
        # A) LEN + intact <IL2P>
        try:
            return try_decode_len_path_mixed(raw, clean, coding)
        except Exception as e:
            last_error = e

        # B) intact <IL2P>...</IL2P>
        try:
            return try_decode_tag_path_mixed(raw, clean, coding)
        except Exception as e:
            last_error = e

        # C) LEN clear, tag damaged, try payload recovery
        try:
            return try_decode_len_recovery_path_mixed(raw, clean, coding)
        except Exception as e:
            last_error = e

    raise ValueError(f"No IL2P binary candidate for codings {detect_coding_candidates(clean)}: {last_error}")

def try_decode_len_path_mixed(raw: str, clean: str, coding: str | None = None) -> bytes:
    m = re.search(r"LEN\D{0,8}(\d{1,4})\D{0,24}<IL2P>", clean)

    if not m:
        raise ValueError("LEN + <IL2P> pattern not found")

    coding = coding or detect_coding(clean)
    expected_len = int(m.group(1))
    payload_start = m.end()
    coded_len = coded_len_for_bytes(expected_len, coding)

    # Fontos: payloadot RAW-ból veszünk, nem clean/upper szövegből.
    tail = raw[payload_start:]

    close_pos = tail.find("<")
    if close_pos >= 0:
        payload_region = tail[:close_pos]
    else:
        payload_region = tail

    payload = collect_coded_from_tail(payload_region, coded_len, coding)

    if len(payload) < coded_len:
        payload = collect_coded_from_tail(tail, coded_len, coding)

    return decode_coded_len_checked(payload, expected_len, coding)


def try_decode_tag_path_mixed(raw: str, clean: str, coding: str | None = None) -> bytes:
    begin = clean.find(BEGIN_TAG)
    coding = coding or detect_coding(clean)

    while begin >= 0:
        end = clean.find(END_TAG, begin + len(BEGIN_TAG))

        if end < 0:
            raise ValueError("END tag not found")

        # Indexek azonosak, mert raw és clean hossza ugyanaz.
        raw_payload = raw[begin + len(BEGIN_TAG):end]

        if coding == "base64":
            payload = filter_base64_strict(raw_payload)
            if len(payload) % 4 != 0:
                raise ValueError(
                    f"Filtered Base64 length is not multiple of 4: {len(payload)}"
                )
            if payload:
                try:
                    return base64.b64decode(payload, validate=False)
                except Exception:
                    pass
        else:
            payload = filter_base32_strict(raw_payload)
            if len(payload) % 8 != 0:
                raise ValueError(
                    f"Filtered Base32 length is not multiple of 8: {len(payload)}"
                )
            if payload:
                try:
                    return base64.b32decode(payload, casefold=True)
                except Exception:
                    pass

        begin = clean.find(BEGIN_TAG, begin + 1)

    raise ValueError(f"No decodable <IL2P>...</IL2P> {coding.upper()} payload found")


def try_decode_len_recovery_path_mixed(raw: str, clean: str, coding: str | None = None) -> bytes:
    candidates = try_decode_len_recovery_candidates_mixed(raw, clean, coding)
    if candidates:
        return candidates[0]
    raise ValueError("LEN recovery failed")


def try_decode_len_recovery_candidates_mixed(raw: str, clean: str, coding: str | None = None) -> list[bytes]:
    m = re.search(r"LEN\D{0,8}(\d{1,4})", clean)

    if not m:
        return []

    coding = coding or detect_coding(clean)
    expected_len = int(m.group(1))
    coded_len = coded_len_for_bytes(expected_len, coding)

    raw_search_area = raw[m.end():]
    clean_search_area = clean[m.end():]

    candidate_starts = []

    # Generic recovery: try multiple possible payload starts after LEN.
    # This handles damaged tags or short junk before payload.
    for off in range(0, 24):
        candidate_starts.append(off)

    p = clean_search_area.find(">")
    if p >= 0:
        candidate_starts.append(p + 1)

    if coding == "base64":
        run_re = r"[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=]{8,}"
    else:
        run_re = r"[ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=]{8,}"

    run = re.search(run_re, raw_search_area)
    if run:
        base = run.start()
        for off in range(0, 32):
            candidate_starts.append(base + off)

    p = clean_search_area.find("<")
    if p >= 0:
        candidate_starts.append(p + 1)

    out = []
    seen_starts = set()

    for start in candidate_starts:
        if start in seen_starts:
            continue
        seen_starts.add(start)

        tail = raw_search_area[start:]

        # Recovery módban sem engedjük, hogy a záró tag betűi
        # belekeveredjenek a kódolt payloadba.
        tag_pos = tail.find("<")
        if tag_pos >= 0:
            tail = tail[:tag_pos]

        payload = collect_coded_from_tail(tail, coded_len, coding)

        if len(payload) < coded_len:
            continue

        try:
            data = decode_coded_len_checked(payload, expected_len, coding)
            out.append(data)
        except Exception:
            pass

    return out

def run_decoder(output_path: str):
    return subprocess.run(
        [sys.executable, "IL2P_decoder_block.py", output_path],
        check=False,
        capture_output=True,
        text=True
    )


def rx_get_data(fldigi) -> str:
    data = fldigi.rx.get_data()

    if data is None:
        return ""

    if isinstance(data, bytes):
        return data.decode("utf-8", errors="ignore")

    return str(data)


def decoder_reject_reason(dec) -> str:
    msg = dec.stderr.strip() or dec.stdout.strip()

    if "HEADER_RS decode failed" in msg:
        return "HEADER_RS decode failed"

    if "PAYLOAD_RS decode failed" in msg:
        return "PAYLOAD_RS decode failed"

    if msg:
        return msg.splitlines()[-1]

    return "unknown decoder error"


def print_success(output_path, data, dec, status1_last="", status2_last="",
                  frame_snr_samples=None, snr_samples=None):
    frame_snr_samples = frame_snr_samples or []
    snr_samples = snr_samples or []

    print()
    print("VALID IL2P FRAME RECEIVED")
    print("WROTE:", output_path)
    print("LEN  :", len(data))

    if status1_last or status2_last:
        print("STATUS1_LAST =", status1_last)
        print("STATUS2_LAST =", status2_last)

    if frame_snr_samples:
        print(
            f"FRAME_AVG_SNR = "
            f"{sum(frame_snr_samples) / len(frame_snr_samples):.1f} dB"
        )
        print(f"FRAME_MIN_SNR = {min(frame_snr_samples):.1f} dB")
        print(f"FRAME_MAX_SNR = {max(frame_snr_samples):.1f} dB")

    if snr_samples:
        print(f"AVG_SNR = {sum(snr_samples) / len(snr_samples):.1f} dB")
        print(f"MIN_SNR = {min(snr_samples):.1f} dB")
        print(f"MAX_SNR = {max(snr_samples):.1f} dB")

    print()
    print("RUN DECODER")
    print(dec.stdout, end="")

    if dec.stderr:
        print(dec.stderr, end="", file=sys.stderr)


def watch_rx(output_path: str, poll_sec: float, max_buffer: int):
    fldigi = connect()

    modem = fldigi.modem.get_name()
    trx = fldigi.main.get_trx_state()

    print("FLDIGI XML-RPC CONNECTED")
    print("MODEM =", modem)
    print("TRX   =", trx)
    print("RXWATCH started")
    print("Output:", output_path)

    rx_buffer = ""

    snr_samples = []
    status1_last = ""
    status2_last = ""

    frame_active = False
    frame_snr_samples = []

    last_error = ""

    while True:
        try:
            try:
                status1_last = str(fldigi.main.get_status1())
                status2_last = str(fldigi.main.get_status2())

                snr = parse_snr_db(status1_last)

                if snr is not None:
                    snr_samples.append(snr)

                    if frame_active:
                        frame_snr_samples.append(snr)

                    if len(snr_samples) > 1000:
                        snr_samples = snr_samples[-1000:]

            except Exception:
                pass

            chunk = rx_get_data(fldigi)

            if chunk:
                print(chunk, end="", flush=True)
                rx_buffer += chunk

                if len(rx_buffer) > max_buffer:
                    rx_buffer = rx_buffer[-max_buffer:]

                clean = clean_text(rx_buffer)

                if not frame_active:
                    if "<IL2P>" in clean or "LEN" in clean:
                        frame_active = True
                        frame_snr_samples = []
                        print()
                        print("FRAME CANDIDATE DETECTED")

                try:
                    candidates = try_extract_il2p_candidates(rx_buffer)

                    if not candidates:
                        if frame_candidate_incomplete(rx_buffer):
                            raise ValueError("Frame incomplete; " + frame_debug_summary(rx_buffer))
                        raise ValueError("No IL2P binary candidate from complete frame; " + frame_debug_summary(rx_buffer))

                    accepted = None
                    accepted_dec = None
                    last_reason = ""

                    for data in candidates:
                        Path(output_path).write_bytes(data)

                        dec = run_decoder(output_path)

                        if dec.returncode == 0:
                            accepted = data
                            accepted_dec = dec
                            break

                        last_reason = decoder_reject_reason(dec)

                    if accepted is None:
                        if last_reason and last_reason != last_error:
                            print()
                            print("Candidate rejected by IL2P decoder:", last_reason)
                            last_error = last_reason

                        time.sleep(poll_sec)
                        continue

                    data = accepted
                    dec = accepted_dec

                    print_success(
                        output_path,
                        data,
                        dec,
                        status1_last,
                        status2_last,
                        frame_snr_samples,
                        snr_samples
                    )
                    return

                except Exception as e:
                    msg = str(e)

                    incomplete = (
                        "pattern not found" in msg
                        or "BEGIN tag not found" in msg
                        or "END tag not found" in msg
                        or "Not enough Base32 data" in msg
                        or "Not enough BASE64 data" in msg
                        or "Not enough BASE32 data" in msg
                        or "No recovery payload start" in msg
                        or "Frame incomplete" in msg
                    )

                    if not incomplete and msg != last_error:
                        print()
                        print("Candidate rejected:", e)
                        last_error = msg

            time.sleep(poll_sec)

        except KeyboardInterrupt:
            print()
            print("Stopped.")
            return

        except Exception as e:
            print()
            print("ERROR:", e)
            time.sleep(1.0)


def watch_text_file(input_path: str, output_path: str, max_buffer: int):
    print("RXWATCH file test mode")
    print("Input :", input_path)
    print("Output:", output_path)

    text = Path(input_path).read_text(encoding="utf-8", errors="ignore")

    rx_buffer = ""
    last_error = ""

    for ch in text:
        rx_buffer += ch

        if len(rx_buffer) > max_buffer:
            rx_buffer = rx_buffer[-max_buffer:]

        try:
            candidates = try_extract_il2p_candidates(rx_buffer)

            if not candidates:
                raise ValueError("No IL2P binary candidate yet")

            accepted = None
            accepted_dec = None
            last_reason = ""

            for data in candidates:
                Path(output_path).write_bytes(data)

                dec = run_decoder(output_path)

                if dec.returncode == 0:
                    accepted = data
                    accepted_dec = dec
                    break

                last_reason = decoder_reject_reason(dec)

            if accepted is None:
                if last_reason and last_reason != last_error:
                    print()
                    print("Candidate rejected by IL2P decoder:", last_reason)
                    last_error = last_reason

                time.sleep(poll_sec)
                continue

            data = accepted
            dec = accepted_dec

            print_success(output_path, data, dec)
            return

        except Exception:
            pass

    print()
    print("No valid IL2P frame found.")


def main():
    parser = argparse.ArgumentParser(
        description="Watch fldigi RX stream and extract IL2P Base32/Base64 frames"
    )

    parser.add_argument(
        "-o",
        "--output",
        default="rx.il2p",
        help="Output IL2P binary file, default: rx.il2p"
    )

    parser.add_argument(
        "--poll",
        type=float,
        default=0.2,
        help="Polling interval in seconds, default: 0.2"
    )

    parser.add_argument(
        "--max-buffer",
        type=int,
        default=20000,
        help="Maximum RX text buffer size, default: 20000"
    )

    parser.add_argument(
        "--input-file",
        help="Read RX character stream from text file instead of fldigi"
    )

    args = parser.parse_args()

    if args.input_file:
        watch_text_file(args.input_file, args.output, args.max_buffer)
    else:
        watch_rx(args.output, args.poll, args.max_buffer)


if __name__ == "__main__":
    main()