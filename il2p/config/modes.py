from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Coding = Literal["base32", "base64", "none"]
AdapterName = Literal["fldigi", "raw", "vara", "ardop"]


@dataclass(frozen=True, slots=True)
class ModeProfile:
    """Application-layer profile.

    The public REST API can name one mode/profile and the application layer
    derives the concrete modem adapter, modem mode, default text coding, FEC
    policy, and station policy from this object.
    """

    name: str
    adapter: AdapterName
    default_coding: Coding = "base64"
    default_fec: int = 1
    max_aprs_payload_bytes: int | None = None
    fldigi_mode: str | None = None
    announce_mode: bool = True       # fldigi TXID / RSID at TX start
    auto_detect_mode: bool = False   # fldigi RXID; usually off for fixed links
    keep_human_readable_frame: bool = True
    description: str = ""
    extra: dict[str, object] = field(default_factory=dict)


def _coding(value: object, default: Coding = "base64") -> Coding:
    s = str(value or default).strip().lower()
    aliases = {"b32": "base32", "b64": "base64", "raw": "none"}
    s = aliases.get(s, s)
    if s not in ("base32", "base64", "none"):
        raise ValueError(f"unsupported coding: {value}")
    return s  # type: ignore[return-value]


def profile_from_config(name: str, raw: dict[str, object]) -> ModeProfile:
    """Build a ModeProfile from YAML config.

    Backward compatible with the previous sprint's keys:
    - modem -> adapter
    - fldigi_mode_hint -> fldigi_mode
    - coding -> default_coding
    - txid/rxid are also accepted as aliases.
    """

    adapter = str(raw.get("adapter", raw.get("modem", "fldigi"))).strip().lower()
    if adapter not in ("fldigi", "raw", "vara", "ardop"):
        raise ValueError(f"unsupported modem adapter for {name}: {adapter}")
    default_fec = int(raw.get("default_fec", raw.get("fec", 1)))
    if default_fec not in (0, 1):
        raise ValueError(f"default_fec must be 0 or 1 for {name}")
    announce_mode = bool(raw.get("announce_mode", raw.get("txid", True)))
    auto_detect_mode = bool(raw.get("auto_detect_mode", raw.get("rxid", False)))
    return ModeProfile(
        name=name,
        adapter=adapter,  # type: ignore[arg-type]
        default_coding=_coding(raw.get("default_coding", raw.get("coding", "base64"))),
        default_fec=default_fec,
        max_aprs_payload_bytes=(None if raw.get("max_aprs_payload_bytes") is None else int(raw["max_aprs_payload_bytes"])),
        fldigi_mode=(str(raw.get("fldigi_mode", raw.get("fldigi_mode_hint"))) if raw.get("fldigi_mode", raw.get("fldigi_mode_hint")) else None),
        announce_mode=announce_mode,
        auto_detect_mode=auto_detect_mode,
        keep_human_readable_frame=bool(raw.get("keep_human_readable_frame", True)),
        description=str(raw.get("description", "")),
        extra={k: v for k, v in raw.items() if k not in {
            "adapter", "modem", "default_coding", "coding", "default_fec", "fec",
            "max_aprs_payload_bytes", "fldigi_mode", "fldigi_mode_hint",
            "announce_mode", "txid", "auto_detect_mode", "rxid",
            "keep_human_readable_frame", "description",
        }},
    )
