from __future__ import annotations

import re


def parse_snr_db(text: str) -> float | None:
    patterns = [r"s/n:\s*([-+]?\d+(?:\.\d+)?)\s*dB", r"SNR\s*=\s*([-+]?\d+(?:\.\d+)?)"]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None
