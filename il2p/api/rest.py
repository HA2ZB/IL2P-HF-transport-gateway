#!/usr/bin/env python3
"""
IL2P / APRS / modem REST service.

Application-layer model introduced in sprint2:
- the REST client chooses a mode/profile, not a low-level modem script;
- the profile derives adapter, fldigi mode, default coding, FEC and TXID/RXID policy;
- TX is half-duplex: pause RX watcher, encode, transmit, return to RX, resync;
- RX is exposed through pollable status and result queues;
- text frames stay human-readable: CALLSIGN IL2P CODING=... LEN=... <IL2P>...</IL2P>.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import re
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from il2p.codec import decode_il2p_frame, encode_il2p_type1_ui, rebuild_ax25_ui_frame
from il2p.config import ModeProfile, profile_from_config
from il2p.framing import decode_frame_text, encode_frame_text
from il2p.modem import FldigiXmlRpcModem, TxOptions
from il2p.runtime import FldigiWatcherService, LinkState, RxDiagnostics, RxStore, RxWatcher


# ---------------------------------------------------------------------------
# Config / service state
# ---------------------------------------------------------------------------

class ServiceState:
    def __init__(self) -> None:
        self.config_path = Path("il2p_gateway.yaml")
        self.config: dict[str, Any] = {}
        self.started_at = time.time()
        self.tx_log: list[dict[str, Any]] = []
        self.rx_store = RxStore(maxlen=500)
        self.watcher_service: FldigiWatcherService | None = None
        self.watcher_profile: str | None = None


state = ServiceState()
app = FastAPI(title="IL2P APRS HF Gateway REST API", version="0.2")


def load_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def cfg_get(path: str, default: Any = None) -> Any:
    cur: Any = state.config
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def all_profiles() -> dict[str, ModeProfile]:
    raw_profiles = cfg_get("mode_profiles", cfg_get("modem_profiles", {}))
    out: dict[str, ModeProfile] = {}
    for name, raw in raw_profiles.items():
        out[name] = profile_from_config(name, raw or {})
    return out


def get_profile(name: str | None) -> ModeProfile:
    profiles = all_profiles()
    if not name:
        name = cfg_get("transport_defaults.profile", cfg_get("transport_defaults.mode"))
    if not name or name not in profiles:
        raise HTTPException(status_code=400, detail=f"Unknown mode/profile: {name}")
    return profiles[name]


def normalize_coding(value: str | None, profile: ModeProfile) -> str:
    coding = (value or cfg_get("transport_defaults.coding", "profile")).lower()
    if coding == "profile":
        coding = profile.default_coding
    aliases = {"b32": "base32", "b64": "base64", "raw": "none"}
    coding = aliases.get(coding, coding)
    if coding not in ("base32", "base64", "none"):
        raise HTTPException(status_code=400, detail="coding must be profile, base32, base64 or none")
    return coding


def normalize_fec(value: int | None, profile: ModeProfile) -> int:
    fec = profile.default_fec if value is None else value
    if fec not in (0, 1):
        raise HTTPException(status_code=400, detail="fec must be 0 or 1")
    return int(fec)


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
        _base, ssid_s = call.split("-", 1)
        ssid = int(ssid_s)
        if not 0 <= ssid <= 15:
            raise HTTPException(status_code=400, detail=f"SSID out of range: {call}")
    return call


def format_aprs_message_addressee(call: str) -> str:
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
    path = [p.strip().upper() for p in (m.group("path") or "").split(",") if p.strip()]
    return {"src": src, "dst": dst, "path": path, "info": m.group("info")}


def parse_aprs_message_info(info: str) -> dict[str, Any]:
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
        return {"aprs_type": kind, "message_to": addressee, "message_text": text, "msgid": msgid}
    return {"aprs_type": "unknown"}


# ---------------------------------------------------------------------------
# fldigi / TX controller
# ---------------------------------------------------------------------------

def fldigi_modem() -> FldigiXmlRpcModem:
    return FldigiXmlRpcModem(cfg_get("fldigi.xmlrpc_url", "http://127.0.0.1:7362"))


def fldigi_status() -> dict[str, Any]:
    try:
        s = fldigi_modem().status()
        return {"connected": True, "modem": s.name, "trx": s.trx, "carrier": s.carrier, "status1": s.status1, "status2": s.status2}
    except Exception as e:
        return {"connected": False, "error": str(e)}


def transmit_text(profile: ModeProfile, text: str) -> None:
    if profile.adapter != "fldigi":
        raise HTTPException(status_code=400, detail=f"TX adapter not implemented for profile {profile.name}: {profile.adapter}")
    watcher_was_running = bool(state.watcher_service and state.watcher_service.running and not state.watcher_service.paused)
    if state.watcher_service:
        state.watcher_service.pause("local transmit")
    try:
        modem = fldigi_modem()
        modem.tx_text(
            text,
            TxOptions(
                mode_name=profile.fldigi_mode,
                announce_mode=profile.announce_mode,
                auto_detect_mode=profile.auto_detect_mode,
                strip_newlines=bool(cfg_get("fldigi.strip_tx_newlines", True)),
                return_to_rx=True,
                rx_resync_delay_s=float(cfg_get("fldigi.rx_resync_delay_s", 0.4)),
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"fldigi TX failed: {e}")
    finally:
        if state.watcher_service and watcher_was_running:
            state.watcher_service.resume("RX watcher resumed after local transmit")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TransportRequest(BaseModel):
    mode: str | None = None
    profile: str | None = None  # backward-compatible alias for mode
    fec: int | None = Field(default=None, ge=0, le=1)
    coding: Literal["profile", "base32", "base64", "none", "b32", "b64", "raw"] | None = None
    tx: bool | None = None
    il2p_destination: str | None = None

    def mode_name(self) -> str | None:
        return self.mode or self.profile


class SendRequest(BaseModel):
    """Generic HF transport payload request.

    This is deliberately not APRS-specific. The payload is carried as the IL2P
    Type-1 information field; higher application layers can build on top of it.
    """

    payload: str
    from_call: str | None = None
    il2p_destination: str | None = None
    transport: TransportRequest = Field(default_factory=TransportRequest)


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


class WatcherStartRequest(BaseModel):
    mode: str | None = None
    profile: str | None = None
    poll_s: float | None = Field(default=None, gt=0, le=10)
    max_buffer: int | None = Field(default=None, ge=1024, le=200000)

    def mode_name(self) -> str | None:
        return self.mode or self.profile


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def encode_pipeline(src: str, dst: str, info: str, tr: TransportRequest) -> dict[str, Any]:
    profile = get_profile(tr.mode_name())
    fec = normalize_fec(tr.fec, profile)
    coding = normalize_coding(tr.coding, profile)
    tx = bool(cfg_get("transport_defaults.tx", True) if tr.tx is None else tr.tx)

    info_bytes = info.encode("ascii", errors="strict")
    if profile.max_aprs_payload_bytes is not None and len(info_bytes) > profile.max_aprs_payload_bytes:
        raise HTTPException(status_code=400, detail=f"APRS payload too long for {profile.name}: {len(info_bytes)} > {profile.max_aprs_payload_bytes}")

    state.rx_store.set_state(LinkState.TX_ENCODING, "local transmit encode" if tx else "encode only")
    ax25, raw_hdr, full_hdr, enc_payload, il2p = encode_il2p_type1_ui(src, dst, info_bytes, fec)
    if coding == "none":
        framed = ""
    else:
        framed = encode_frame_text(il2p, coding=coding, callsign=src.split("-")[0])

    if tx and coding == "none":
        state.rx_store.set_state(LinkState.ERROR, "coding=none cannot be sent through fldigi text XML-RPC")
        raise HTTPException(status_code=400, detail="coding=none cannot be sent through fldigi text XML-RPC")

    if tx:
        state.rx_store.set_state(LinkState.TX_ACTIVE, "local transmit")
        transmit_text(profile, framed)
        state.rx_store.set_state(LinkState.RX_RESYNC, "post-TX RX buffer flush")
        state.rx_store.set_state(LinkState.IDLE, "RX watcher resumed")
    else:
        state.rx_store.set_state(LinkState.IDLE, "encode only complete")

    record = {
        "id": str(uuid.uuid4()),
        "ts": time.time(),
        "src": src,
        "dst": dst,
        "info": info,
        "mode": profile.name,
        "adapter": profile.adapter,
        "fldigi_mode": profile.fldigi_mode,
        "announce_mode": profile.announce_mode,
        "auto_detect_mode": profile.auto_detect_mode,
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
        "ax25_hex": ax25.hex(" ").upper(),
    }


def decode_il2p_to_result(il2p: bytes, *, coding: str | None = None, raw_text_excerpt: str | None = None) -> dict[str, Any]:
    try:
        decoded = decode_il2p_frame(il2p)
        ax25 = rebuild_ax25_ui_frame(decoded)
        result = state.rx_store.append_result(
            valid=True,
            coding=coding,
            src=f"{decoded['src']}-{decoded['src_ssid']}",
            dst=f"{decoded['dst']}-{decoded['dst_ssid']}",
            aprs_text=decoded["aprs_text"],
            fec=decoded["fec_level"],
            il2p_len=len(il2p),
            raw_text_excerpt=raw_text_excerpt,
        )
        return {
            "ok": True,
            "rx": result.as_dict(detailed=True),
            "aprs": parse_aprs_message_info(decoded["aprs_text"]),
            "ax25_rebuilt_hex": ax25.hex(" ").upper(),
        }
    except Exception as e:
        result = state.rx_store.append_result(
            valid=False,
            coding=coding,
            il2p_len=len(il2p),
            raw_text_excerpt=raw_text_excerpt,
            reason=str(e),
            diagnostics=RxDiagnostics(),
        )
        raise HTTPException(status_code=400, detail={"error": str(e), "rx_result": result.as_dict(detailed=True)})


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "uptime_s": round(time.time() - state.started_at, 1), "gateway": cfg_get("gateway", {}), "fldigi": fldigi_status()}


@app.get("/status")
def status() -> dict[str, Any]:
    return {
        "state": state.rx_store.state,
        "reason": state.rx_store.state_reason,
        "rx_active": state.rx_store.rx_active,
        "tx_active": state.rx_store.tx_active,
        "last_result_id": state.rx_store.last_result_id,
        "watcher": {
            "running": bool(state.watcher_service and state.watcher_service.running),
            "paused": bool(state.watcher_service and state.watcher_service.paused),
            "profile": state.watcher_profile,
        },
        "fldigi": fldigi_status(),
    }


@app.get("/modes")
def modes() -> dict[str, Any]:
    """List mode profiles. This is the frozen public endpoint."""
    return {
        "default": cfg_get("transport_defaults.profile", cfg_get("transport_defaults.mode")),
        "modes": {name: asdict(p) for name, p in all_profiles().items()},
    }


@app.get("/modes/{mode_name}")
def mode_detail(mode_name: str) -> dict[str, Any]:
    profiles = all_profiles()
    if mode_name not in profiles:
        raise HTTPException(status_code=404, detail="Mode/profile not found")
    return asdict(profiles[mode_name])


# Backward-compatible alias from sprint2/3.
@app.get("/profiles")
def profiles() -> dict[str, Any]:
    m = modes()
    return {"default": m["default"], "profiles": m["modes"]}


@app.post("/send")
def post_send(req: SendRequest) -> dict[str, Any]:
    """Generic HF transport send.

    The request payload is not interpreted as APRS. APRS-specific helpers are
    exposed separately under /send/aprs.
    """
    src = normalize_call(req.from_call or cfg_get("gateway.callsign", "NOCALL-0"))
    tr = req.transport
    if req.il2p_destination and not tr.il2p_destination:
        tr.il2p_destination = req.il2p_destination
    dst = normalize_call(tr.il2p_destination or cfg_get("aprs.default_il2p_destination", "APRS"))
    result = encode_pipeline(src, dst, req.payload, tr)
    result["normalized"] = {"src": src, "il2p_destination": dst, "payload": req.payload, "application": "generic"}
    return result


@app.post("/send/aprs")
def post_send_aprs(req: MessageRequest) -> dict[str, Any]:
    src = normalize_call(req.from_call or cfg_get("gateway.callsign", "NOCALL-0"))
    dst = normalize_call(req.transport.il2p_destination or cfg_get("aprs.default_il2p_destination", "APRS"))
    info = make_aprs_message(req.to, req.text, req.msgid)
    result = encode_pipeline(src, dst, info, req.transport)
    result["normalized"] = {"src": src, "il2p_destination": dst, "aprs_info": info, "application": "aprs", **parse_aprs_message_info(info)}
    return result


# Backward-compatible alias from sprint3.
@app.post("/message")
def post_message(req: MessageRequest) -> dict[str, Any]:
    return post_send_aprs(req)


@app.post("/send/aprs/raw")
def post_send_raw_aprs(req: RawAprsRequest) -> dict[str, Any]:
    parsed = parse_tnc2(req.packet)
    path_warning = "TNC2 path was parsed but is not carried in IL2P Type-1 frame" if parsed["path"] else None
    result = encode_pipeline(parsed["src"], parsed["dst"], parsed["info"], req.transport)
    result["normalized"] = {**parsed, **parse_aprs_message_info(parsed["info"]), "warning": path_warning, "application": "aprs"}
    return result


# Backward-compatible alias from sprint3.
@app.post("/tx_raw_aprs")
def post_tx_raw_aprs(req: RawAprsRequest) -> dict[str, Any]:
    return post_send_raw_aprs(req)


@app.post("/decode")
def decode(req: DecodeRequest) -> dict[str, Any]:
    try:
        coding = req.coding
        if req.framed_text is not None:
            il2p = decode_frame_text(req.framed_text, preferred=coding)  # tolerant parser
            coding = coding or "auto"
            raw_excerpt = req.framed_text[:200]
        elif req.il2p_base64 is not None:
            il2p = base64.b64decode(req.il2p_base64)
            raw_excerpt = None
        elif req.il2p_hex is not None:
            il2p = bytes.fromhex(req.il2p_hex.replace(",", " ").replace("0x", ""))
            raw_excerpt = None
        else:
            raise HTTPException(status_code=400, detail="Provide framed_text, il2p_base64 or il2p_hex")
        return decode_il2p_to_result(il2p, coding=coding, raw_text_excerpt=raw_excerpt)
    except binascii.Error as e:
        result = state.rx_store.append_result(valid=False, reason=f"Invalid binary encoding: {e}")
        raise HTTPException(status_code=400, detail={"error": f"Invalid binary encoding: {e}", "rx_result": result.as_dict(detailed=True)})
    except HTTPException:
        raise


@app.post("/rx/watch/start")
def rx_watch_start(req: WatcherStartRequest) -> dict[str, Any]:
    profile = get_profile(req.mode_name())
    if profile.adapter != "fldigi":
        raise HTTPException(status_code=400, detail=f"RX watcher adapter not implemented for profile {profile.name}: {profile.adapter}")
    if state.watcher_service and state.watcher_service.running:
        return {"ok": True, "already_running": True, "profile": state.watcher_profile}

    modem = fldigi_modem()
    try:
        modem.set_mode(profile.fldigi_mode or "")
        modem.set_id_policy(announce_mode=profile.announce_mode, auto_detect_mode=profile.auto_detect_mode)
        modem.clear_rx()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"fldigi RX watcher setup failed: {e}")

    watcher = RxWatcher(
        state.rx_store,
        mode=profile.name,
        max_buffer=int(req.max_buffer or cfg_get("rx.max_buffer", 20000)),
    )
    state.watcher_service = FldigiWatcherService(
        modem,
        watcher,
        poll_s=float(req.poll_s or cfg_get("rx.poll_s", 0.2)),
    )
    state.watcher_profile = profile.name
    state.watcher_service.start()
    return {"ok": True, "running": True, "profile": profile.name}


@app.post("/rx/watch/stop")
def rx_watch_stop() -> dict[str, Any]:
    if state.watcher_service:
        state.watcher_service.stop()
    state.watcher_service = None
    old_profile = state.watcher_profile
    state.watcher_profile = None
    return {"ok": True, "running": False, "profile": old_profile}


@app.post("/rx/watch/pause")
def rx_watch_pause() -> dict[str, Any]:
    if not state.watcher_service or not state.watcher_service.running:
        raise HTTPException(status_code=400, detail="RX watcher is not running")
    state.watcher_service.pause("manual pause")
    return {"ok": True, "paused": True}


@app.post("/rx/watch/resume")
def rx_watch_resume() -> dict[str, Any]:
    if not state.watcher_service or not state.watcher_service.running:
        raise HTTPException(status_code=400, detail="RX watcher is not running")
    state.watcher_service.resume("manual resume")
    return {"ok": True, "paused": False}


# Frozen public watcher endpoints. The /rx/watch/* paths remain accepted.
@app.post("/watch/start")
def watch_start(req: WatcherStartRequest) -> dict[str, Any]:
    return rx_watch_start(req)


@app.post("/watch/stop")
def watch_stop() -> dict[str, Any]:
    return rx_watch_stop()


@app.post("/watch/pause")
def watch_pause() -> dict[str, Any]:
    return rx_watch_pause()


@app.post("/watch/resume")
def watch_resume() -> dict[str, Any]:
    return rx_watch_resume()


@app.get("/rx/results")
def rx_results(since: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=500), detailed: bool = False) -> dict[str, Any]:
    return {"items": state.rx_store.list_results(since=since, limit=limit, detailed=detailed), "last_result_id": state.rx_store.last_result_id}


@app.get("/rx/results/{result_id}")
def rx_result(result_id: int) -> dict[str, Any]:
    result = state.rx_store.get_result(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="RX result not found")
    return result.as_dict(detailed=True)


@app.get("/statistics")
def statistics() -> dict[str, Any]:
    results = list(state.rx_store.results)
    ok = [r for r in results if r.valid]
    bad = [r for r in results if not r.valid]
    snr_vals = [r.diagnostics.snr_avg for r in results if r.diagnostics and r.diagnostics.snr_avg is not None]
    snr_min_vals = [r.diagnostics.snr_min for r in results if r.diagnostics and r.diagnostics.snr_min is not None]
    return {
        "frames_ok": len(ok),
        "frames_bad": len(bad),
        "frames_total": len(results),
        "last_result_id": state.rx_store.last_result_id,
        "tx_count": len(state.tx_log),
        "snr_avg": (sum(snr_vals) / len(snr_vals) if snr_vals else None),
        "snr_min": (min(snr_min_vals) if snr_min_vals else None),
    }


@app.get("/config")
def get_config() -> dict[str, Any]:
    return state.config


@app.post("/config")
def update_config(patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow in-memory config update for lab use.

    Persistent config editing should still be done in il2p_gateway.yaml until a
    stronger validation/persistence layer is introduced.
    """
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(state.config.get(k), dict):
            state.config[k].update(v)
        else:
            state.config[k] = v
    return state.config


@app.get("/tx_log")
def tx_log() -> dict[str, Any]:
    return {"items": list(reversed(state.tx_log[-50:]))}


# Compatibility alias from sprint1.
@app.get("/rx_log")
def rx_log() -> dict[str, Any]:
    return {"items": state.rx_store.list_results(limit=50, detailed=True)}


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
