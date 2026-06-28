from __future__ import annotations

import re


def normalize_call(call: str) -> str:
    return call.strip().upper()


def format_aprs_message_addressee(call: str) -> str:
    return normalize_call(call).ljust(9)[:9]


def make_aprs_message(to: str, text: str, msg_id: str | None = None) -> bytes:
    body = f":{format_aprs_message_addressee(to)}:{text}"
    if msg_id:
        body += "{" + msg_id
    return body.encode("ascii", errors="replace")


def parse_tnc2(line: str) -> dict[str, str]:
    m = re.match(r"^([^>]+)>([^:]+):(.+)$", line.strip())
    if not m:
        raise ValueError("Invalid TNC2 line")
    return {"src": m.group(1), "path": m.group(2), "info": m.group(3)}


def parse_aprs_message_info(info: str) -> dict[str, str] | None:
    if not info.startswith(":") or len(info) < 11:
        return None
    addressee = info[1:10].strip()
    rest = info[10:]
    if not rest.startswith(":"):
        return None
    body = rest[1:]
    msg_id = ""
    if "{" in body:
        body, msg_id = body.rsplit("{", 1)
    return {"to": addressee, "text": body, "id": msg_id}
