#!/usr/bin/env python3
"""
IL2P / APRS / fldigi REST service

This service wraps the existing project modules:
  - IL2P_encoder_block.py
  - IL2P_decoder_block.py
  - IL2P_fldigi_frame.py concepts
  - fldigi XML-RPC TX path

Run:
  pip install fastapi uvicorn pyyaml reedsolo
  python IL2P_rest_service.py --config il2p_gateway.yaml

Then open:
  http://127.0.0.1:8080/docs
"""

from __future__ import annotations

import argparse
import base64
import binascii
import re
import time
import uuid
import xmlrpc.client
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from IL2P_encoder_block import encode_il2p_type1_ui
from IL2P_decoder_block import decode_il2p_frame, rebuild_ax25_ui_frame


BEGIN_TAG = "<IL2P>"
END_TAG = "</IL2P>"
BASE32_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=")
BASE64_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class ServiceState:
    def __init__(self) -> None:
        self.config_path = Path("il2p_gateway.yaml")
        self.config: dict[str, Any] = {}
        self.started_at = time.time()
        self.tx_log: list[dict[str, Any]] = []
        self.rx_log: list[dict[str, Any]] = []


state = ServiceState()
app = FastAPI(title="IL2P APRS HF Gateway REST API", version="0.1")


def load_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data


def cfg_get(path: str, default: Any = None) -> Any:
    cur: Any = state.config
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def get_profile(name: str | None) -> tuple[str, dict[str, Any]]:
    profiles = cfg_get("modem_profiles", {})
    if not name:
        name = cfg_get("transport_defaults.profile")
    if name not in profiles:
        raise HTTPException(status_code=400, detail=f"Unknown transport profile: {name}")
    return name, profiles[name]


def resolve_fec(profile: dict[str, Any], requested_fec: int | None) -> int:
    fec = requested_fec
    if fec is None:
        fec = profile.get("default_fec", cfg_get("transport_defaults.fec", 1))
    if fec not in (0, 1):
        raise HTTPException(status_code=400, detail="fec must be 0 or 1")
    return int(fec)


def resolve_coding(profile: dict[str, Any], requested_coding: str | None) -> str:
    coding = requested_coding or cfg_get("transport_defaults.coding", "profile")
    coding = coding.lower()
    if coding == "profile":
        coding = str(profile.get("coding", "base32")).lower()
    aliases = {"b32": "base32", "b64": "base64", "raw": "none"}
    coding = aliases.get(coding, coding)
    if coding not in ("base32", "base64", "none"):
        raise HTTPException(status_code=400, detail="coding must be base32, base64 or none")
    return coding


# ---------------------------------------------------------------------------
# APRS / TNC2 helpers
# ---------------------------------------------------------------------------

CALL_RE = re.compile(r"^[A-Z0-9]{1,6}(?:-[0-9]{1,2})?$")
TNC2_RE = re.compile(r"^(?P<src>[^>]+)>(?P<dst>[^:,]+)(?P<path>(?:,[^:]+)*)?:(?P<info>.*)$")


def normalize_call(call: str) -> str:
    call = call.strip().upper()
    if not CALL_RE.match(call):
        raise HTTPException(status_code=400, detail=f"Invalid callsign/SSID: {call}")
    if "-" in call:
        base, ssid_s = call.split("-", 1)
        ssid = int(ssid_s)
        if not 0 <= ssid <= 15:
            raise HTTPException(status_code=400, detail=f"SSID out of range: {call}")
    return call


def format_aprs_message_addressee(call: str) -> str:
    # APRS message addressee is exactly 9 characters.
    call = normalize_call(call)
    if len(call) > 9:
        raise HTTPException(status_code=400, detail="APRS message addressee is longer than 9 chars")
    return call.ljust(9)


def make_aprs_message(to_call: str, text: str, msgid: str | None = None) -> str:
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")
    info = f":{format_aprs_message_addressee(to_call)}:{text}"
    if msgid:
        msgid = str(msgid).strip()
        if not re.match(r"^[A-Za-z0-9]{1,5}$", msgid):
            raise HTTPException(status_code=400, detail="msgid should be 1..5 alphanumeric chars")
        info += "{" + msgid
    return info


def parse_tnc2(packet: str) -> dict[str, Any]:
    m = TNC2_RE.match(packet.strip())
    if not m:
        raise HTTPException(status_code=400, detail="Invalid TNC2 packet format")
    src = normalize_call(m.group("src"))
    dst = normalize_call(m.group("dst"))
    path = []
    if m.group("path"):
        path = [p.strip().upper() for p in m.group("path").split(",") if p.strip()]
    info = m.group("info")
    return {"src": src, "dst": dst, "path": path, "info": info}


def parse_aprs_message_info(info: str) -> dict[str, Any]:
    # :ADDRESSEE:message{123
    if len(info) >= 11 and info.startswith(":") and info[10] == ":":
        addressee = info[1:10].strip()
        body = info[11:]
        msgid = None
        if "{" in body:
            text, msgid = body.rsplit("{", 1)
        else:
            text = body
        kind = "message"
        if text.startswith("ack"):
            kind = "ack"
        elif text.startswith("rej"):
            kind = "rej"
        return {
            "aprs_type": kind,
            "message_to": addressee,
            "message_text": text,
            "msgid": msgid,
        }
    return {"aprs_type": "unknown"}


def split_call_ssid(full: str) -> tuple[str, int]:
    full = normalize_call(full)
    if "-" in full:
        c, s = full.split("-", 1)
        return c, int(s)
    return full, 0


# ---------------------------------------------------------------------------
# Framing / coding
# ---------------------------------------------------------------------------

def frame_text(data: bytes, coding: str, src: str) -> str:
    src_call = src.split("-")[0].upper()

    if coding == "base32":
        payload = base64.b32encode(data).decode("ascii")
        return f"{src_call} IL2P CODING=BASE32 LEN={len(data)} {BEGIN_TAG}{payload}{END_TAG}"

    if coding == "base64":
        payload = base64.b64encode(data).decode("ascii")
        return f"{src_call} IL2P CODING=BASE64 LEN={len(data)} {BEGIN_TAG}{payload}{END_TAG}"
        
    if coding == "none":
        # REST/JSON cannot safely carry arbitrary binary as a TX text string.
        # The raw bytes are returned separately as hex/base64 in the response.
        return ""
    raise ValueError(f"Unsupported coding: {coding}")


def extract_coded_text(text: str, coding_hint: str | None = None) -> bytes:
    clean = "".join(text.split())
    clean_upper = clean.upper()

    coding = coding_hint.lower() if coding_hint else None
    if coding in ("b32",):
        coding = "base32"
    if coding in ("b64",):
        coding = "base64"

    if coding is None:
        m_coding = re.search(r"CODING=(B32|BASE32|B64|BASE64)", clean_upper)
        if m_coding:
            v = m_coding.group(1)
            coding = "base32" if "32" in v else "base64"
        else:
            coding = "base32"

    m_len = re.search(r"LEN\D{0,8}(\d{1,4})", clean_upper)
    expected_len = int(m_len.group(1)) if m_len else None

    begin = clean_upper.find(BEGIN_TAG)
    if begin < 0:
        raise HTTPException(status_code=400, detail="BEGIN tag not found")
    start = begin + len(BEGIN_TAG)
    end = clean_upper.find(END_TAG, start)
    payload_region = clean[start:end] if end >= 0 else clean[start:]

    if coding == "base32":
        payload = "".join(ch for ch in payload_region.upper() if ch in BASE32_ALLOWED)
        if expected_len is not None:
            need = ((expected_len + 4) // 5) * 8
            payload = payload[:need]
        data = base64.b32decode(payload, casefold=True)
    elif coding == "base64":
        payload = "".join(ch for ch in payload_region if ch in BASE64_ALLOWED)
        data = base64.b64decode(payload, validate=False)
    else:
        raise HTTPException(status_code=400, detail="Text decode supports base32/base64 only")

    if expected_len is not None and len(data) != expected_len:
        raise HTTPException(status_code=400, detail=f"Length mismatch: expected {expected_len}, got {len(data)}")
    return data


# ---------------------------------------------------------------------------
# fldigi XML-RPC
# ---------------------------------------------------------------------------

def fldigi_connect() -> xmlrpc.client.ServerProxy:
    return xmlrpc.client.ServerProxy(cfg_get("fldigi.xmlrpc_url", "http://127.0.0.1:7362"), allow_none=True)


def fldigi_status() -> dict[str, Any]:
    try:
        f = fldigi_connect()
        return {
            "connected": True,
            "modem": str(f.modem.get_name()),
            "trx": str(f.main.get_trx_state()),
            "status1": str(f.main.get_status1()),
            "status2": str(f.main.get_status2()),
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


def fldigi_tx_text(text: str) -> None:
    if cfg_get("fldigi.strip_tx_newlines", True):
        text = text.replace("\r", "").replace("\n", "")
    try:
        f = fldigi_connect()
        f.text.clear_tx()
        f.text.add_tx(text)
        f.main.tx()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"fldigi TX failed: {e}")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TransportRequest(BaseModel):
    profile: str | None = None
    fec: int | None = Field(default=None, ge=0, le=1)
    coding: Literal["profile", "base32", "base64", "none", "b32", "b64", "raw"] | None = None
    tx: bool | None = None
    il2p_destination: str | None = None


class MessageRequest(BaseModel):
    to: str
    text: str
    msgid: str | None = None
    from_call: str | None = None
    transport: TransportRequest = Field(default_factory=TransportRequest)


class RawAprsRequest(BaseModel):
    packet: str
    transport: TransportRequest = Field(default_factory=TransportRequest)


class DecodeRequest(BaseModel):
    il2p_hex: str | None = None
    il2p_base64: str | None = None
    framed_text: str | None = None
    coding: Literal["base32", "base64", "b32", "b64"] | None = None


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def encode_pipeline(src: str, dst: str, info: str, tr: TransportRequest) -> dict[str, Any]:
    profile_name, profile = get_profile(tr.profile)
    fec = resolve_fec(profile, tr.fec)
    coding = resolve_coding(profile, tr.coding)
    tx = cfg_get("transport_defaults.tx", True) if tr.tx is None else tr.tx

    max_len = profile.get("max_aprs_payload_bytes")
    info_bytes = info.encode("ascii", errors="strict")
    if max_len is not None and len(info_bytes) > int(max_len):
        raise HTTPException(status_code=400, detail=f"APRS payload too long for profile {profile_name}: {len(info_bytes)} > {max_len}")

    _, raw_hdr, full_hdr, enc_payload, il2p = encode_il2p_type1_ui(src, dst, info_bytes, fec)
    framed = frame_text(il2p, coding, src)

    if tx and coding == "none":
        raise HTTPException(status_code=400, detail="coding=none cannot be sent through fldigi text XML-RPC")

    if tx:
        fldigi_tx_text(framed)

    record = {
        "id": str(uuid.uuid4()),
        "ts": time.time(),
        "src": src,
        "dst": dst,
        "info": info,
        "profile": profile_name,
        "fec": fec,
        "coding": coding,
        "tx_requested": tx,
        "il2p_len": len(il2p),
        "framed_len": len(framed),
    }
    state.tx_log.append(record)
    state.tx_log = state.tx_log[-200:]

    return {
        "ok": True,
        "tx": record,
        "il2p": {
            "len": len(il2p),
            "hex": il2p.hex(" ").upper(),
            "base64": base64.b64encode(il2p).decode("ascii"),
            "header_raw_hex": raw_hdr.hex(" ").upper(),
            "header_encoded_hex": full_hdr.hex(" ").upper(),
            "payload_encoded_hex": enc_payload.hex(" ").upper(),
        },
        "framed_text": framed,
    }


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "uptime_s": round(time.time() - state.started_at, 1),
        "gateway": cfg_get("gateway", {}),
        "fldigi": fldigi_status(),
    }


@app.get("/profiles")
def profiles() -> dict[str, Any]:
    return {
        "default": cfg_get("transport_defaults.profile"),
        "profiles": cfg_get("modem_profiles", {}),
    }


@app.post("/message")
def post_message(req: MessageRequest) -> dict[str, Any]:
    src = normalize_call(req.from_call or cfg_get("gateway.callsign", "NOCALL-0"))
    dst = normalize_call(req.transport.il2p_destination or cfg_get("aprs.default_il2p_destination", "APRS"))
    info = make_aprs_message(req.to, req.text, req.msgid)
    result = encode_pipeline(src, dst, info, req.transport)
    result["normalized"] = {
        "src": src,
        "il2p_destination": dst,
        "aprs_info": info,
        **parse_aprs_message_info(info),
    }
    return result


@app.post("/tx_raw_aprs")
def post_tx_raw_aprs(req: RawAprsRequest) -> dict[str, Any]:
    parsed = parse_tnc2(req.packet)
    if parsed["path"]:
        # IL2P type-1 frame does not carry AX.25 path. Keep it visible,
        # but do not claim to transport it.
        path_warning = "TNC2 path was parsed but is not carried in IL2P Type-1 frame"
    else:
        path_warning = None
    result = encode_pipeline(parsed["src"], parsed["dst"], parsed["info"], req.transport)
    result["normalized"] = {
        **parsed,
        **parse_aprs_message_info(parsed["info"]),
        "warning": path_warning,
    }
    return result


@app.post("/decode")
def decode(req: DecodeRequest) -> dict[str, Any]:
    try:
        if req.framed_text is not None:
            il2p = extract_coded_text(req.framed_text, req.coding)
        elif req.il2p_base64 is not None:
            il2p = base64.b64decode(req.il2p_base64)
        elif req.il2p_hex is not None:
            il2p = bytes.fromhex(req.il2p_hex.replace(",", " ").replace("0x", ""))
        else:
            raise HTTPException(status_code=400, detail="Provide framed_text, il2p_base64 or il2p_hex")

        decoded = decode_il2p_frame(il2p)
        ax25 = rebuild_ax25_ui_frame(decoded)
        record = {
            "id": str(uuid.uuid4()),
            "ts": time.time(),
            "src": f"{decoded['src']}-{decoded['src_ssid']}",
            "dst": f"{decoded['dst']}-{decoded['dst_ssid']}",
            "aprs_text": decoded["aprs_text"],
            "fec": decoded["fec_level"],
            "il2p_len": len(il2p),
        }
        state.rx_log.append(record)
        state.rx_log = state.rx_log[-200:]
        return {
            "ok": True,
            "rx": record,
            "aprs": parse_aprs_message_info(decoded["aprs_text"]),
            "ax25_rebuilt_hex": ax25.hex(" ").upper(),
        }
    except binascii.Error as e:
        raise HTTPException(status_code=400, detail=f"Invalid binary encoding: {e}")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/tx_log")
def tx_log() -> dict[str, Any]:
    return {"items": list(reversed(state.tx_log[-50:]))}


@app.get("/rx_log")
def rx_log() -> dict[str, Any]:
    return {"items": list(reversed(state.rx_log[-50:]))}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="IL2P APRS HF Gateway REST service")
    parser.add_argument("--config", default="il2p_gateway.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    state.config_path = Path(args.config)
    state.config = load_config(state.config_path)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
