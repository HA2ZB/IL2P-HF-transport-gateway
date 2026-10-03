# IL2P HF Transport Gateway

> **Open-source HF transport engine for IL2P messaging over modern narrow-band amateur radio digital modes.**

> **Project status (Sprint 4.1)**
>
> ✅ End-to-end HF transport operational
>
> ✅ REST-controlled transmission and reception
>
> ✅ Validated over Olivia and Contestia using fldigi
>
> ⚠ Experimental software – API and internal architecture may still evolve.

---

## Overview

IL2P HF Transport Gateway is an experimental but rapidly evolving open-source project implementing a complete HF transport layer based on the open IL2P protocol.

The project currently combines:

- Native IL2P Type-1 implementation
- Reed-Solomon FEC
- fldigi modem backend
- Olivia and Contestia digital modes
- Automatic Base32 / Base64 framing selection
- REST API
- Background RX watcher
- Continuous Integration (GitHub Actions)
- Automated regression tests

The long-term goal is to provide a completely open alternative for HF packet transport that is independent of proprietary modem technologies.

---

# Current Architecture

```
Application Layer
        │
        ▼
 REST API
        │
        ▼
 IL2P Core
 ├── APRS
 ├── Registry
 ├── Routing
 ├── ACK / Retry
 ├── Framing
 ├── Diagnostics
 └── Modem Abstraction
        │
        ▼
 fldigi XML-RPC
```

The transport layer is intentionally independent from APRS. APRS is treated as one possible application protocol running over IL2P.

---

# Sprint 3

Sprint 3 introduced the runtime communication model.

## Added

- Background RX watcher service
- Half-duplex TX/RX controller
- Automatic watcher pause during transmission
- Automatic resume after TX
- Runtime RX result queue
- Frame detection pipeline
- Pollable REST status model
- RX state machine

The receiver continuously monitors fldigi output while applications communicate only through the REST API.

---

# Sprint 4 / 4.1

Sprint 4 established the public REST architecture, while Sprint 4.1 completed the first stable end-to-end radio operation.

## Added

- Stable REST endpoints
- REST-first architecture
- Bruno API collection
- GitHub Actions CI
- Expanded automated tests
- Canonical human-readable over-the-air framing
- Automatic TX → RX handling
- Continuous RX watcher operation
- Pollable RX results
- Runtime diagnostics (SNR, frequency offset, RS statistics)
- Stable watcher state machine
- End-to-end TX/RX validation over fldigi

Canonical transmitted frame:

```
<CALLSIGN> IL2P CODING=BASE32|BASE64 LEN=<n> <IL2P>...</IL2P>
```

This intentionally keeps every transmission identifiable as amateur-radio digital traffic.

---

# Mode Profiles

Applications no longer configure modem parameters individually.

Instead they simply select a mode profile.

```yaml
mode: OLIVIA-4-250
```

A mode profile automatically defines:

- modem backend
- fldigi mode
- default framing
- FEC policy
- TXID (announce mode)
- RXID policy
- human-readable frame policy

Current defaults:

| Mode | Framing | TXID |
|------|----------|------|
| Olivia 4/250 | Base64 | enabled |
| Contestia 4/250 | Base32 | enabled |

RXID is intentionally disabled because both endpoints already know the negotiated mode.

Mode profiles fully define the Layer-1 operational behaviour, allowing applications to remain completely modem-independent.

---

# REST API

Main endpoints:

```
GET  /status

POST /watch/start
POST /watch/stop
POST /watch/pause
POST /watch/resume

POST /send
POST /send/aprs

GET  /rx/results
GET  /rx/results/{id}

GET  /statistics

GET  /modes
```

The REST API represents the Application Layer.

Applications never interact directly with fldigi or IL2P internals.

The REST interface now provides complete control over transmission, reception and runtime monitoring.

---

# Testing

Run locally:

```bash
python -m pytest -v
```

GitHub Actions executes the same test suite automatically after every push and pull request.

The regression suite currently covers:

- IL2P encode/decode roundtrip
- Base32/Base64 framing
- REST API
- Mode profiles
- RX watcher
- Runtime state transitions
- TX pause / RX resume behaviour

---

# Current Status

## Implemented

- Native IL2P Type-1 encoder / decoder
- AX.25 compatibility
- Reed-Solomon FEC (FEC0 / FEC1)
- Base32 / Base64 framing
- fldigi XML-RPC integration
- Automatic mode profile selection
- Automatic coding detection
- Continuous RX watcher
- Pollable RX result queue
- Runtime diagnostics
  - SNR
  - Frequency offset
  - Reed-Solomon correction statistics
- REST API
- Bruno API collection
- Mode profiles
- Half-duplex runtime controller
- Automatic TX → RX return
- Human-readable over-the-air framing
- GitHub Actions CI
- Automated regression tests

Validated end-to-end operation has been successfully demonstrated over Olivia and Contestia using the complete transport chain:

```
REST API
    ↓
IL2P Core
    ↓
fldigi XML-RPC
    ↓
HF Digital Modem
    ↓
fldigi RX
    ↓
IL2P Decoder
    ↓
REST RX Results
```

---

# Roadmap

Next milestones:

- APRS application layer
- Registry service
- ACK / Retry manager
- Gateway routing
- APRS-IS integration
- Store-and-forward
- Node-RED integration
- Additional modem adapters

------------------------------------------------------------------------

## License

This project is licensed under the **GNU General Public License v2.0 or
later (GPL-2.0-or-later)**.

See the `LICENSE` file for details.

This project is intended as a practical utility for the amateur radio
community.

This project was developed by the author with iterative assistance from
AI-based coding tools.

------------------------------------------------------------------------

## Acknowledgements

Parts of the IL2P implementation were developed based on concepts and
source code from the **Dire Wolf** project by **John Langner (WB2OSZ)**.

Dire Wolf is licensed under the GNU General Public License v2.0 (GPL-2.0).
Where applicable, this project complies with the corresponding GPL license
requirements.

## Contributing

Contributions, testing, documentation improvements and implementation
ideas are welcome.

The long-term objective is to provide a completely open HF digital
transport platform built around IL2P and standard amateur radio
software.

## Binary modem backend API

`il2p.modem.ModemBackend` defines `status()`, `set_mode(name)`,
`send(data: bytes, options)` and `receive() -> bytes`. Each send carries one
complete binary IL2P frame. Receive returns one complete frame, or `b""` when
no frame is available. Adapters retain partial transport data between polls;
a malformed transport frame is consumed and raises `ValueError`, allowing
later frames to be read. Transport delivery does not imply an APRS or
application acknowledgement.

The fldigi adapter owns Base32/Base64 encoding and canonical text framing.
The REST TX path passes binary IL2P to `send()`; its `framed_text` preview
uses the same adapter formatter. Raw (`none`) coding remains unavailable for
fldigi TX. Existing profile names and REST response fields are preserved.

`Modem` remains an alias for `ModemBackend`. Fldigi's `tx_text()` and
`rx_text()` remain adapter-specific compatibility helpers. The existing
fldigi watcher deliberately continues using the text stream to preserve
candidate timeouts, malformed-frame results, and SNR sampling while a frame
is arriving. Do not mix `receive()` and `rx_text()` on the same adapter
instance: both consume the same incoming stream. Packet RX clients must
reuse an adapter instance across polls.

Status adds `backend`, `mode`, `state`, `snr_db`, `bitrate_bps`, and `details`
while preserving legacy fldigi fields. Unknown metrics remain `None`.
Mercury KISS/TCP broadcast is also supported, with a separate binary RX
watcher. Mercury ARQ is a later step.

## Mercury KISS/TCP broadcast

The adapter was checked against Mercury **v1.9.15**, commit
`8a47831882c9751b1fee5bcbf5f9de11fb46ac4b`:

- [KISS commands and escaping](https://github.com/Rhizomatica/mercury/blob/v1.9.15/datalink_broadcast/kiss.h)
- [TCP broadcast wrapping and RX delivery](https://github.com/Rhizomatica/mercury/blob/v1.9.15/data_interfaces/tcp_interfaces.c)
- [Mode frame capacities](https://github.com/Rhizomatica/mercury/blob/v1.9.15/datalink_broadcast/bcast_modes.h)
- [Port configuration](https://github.com/Rhizomatica/mercury/blob/v1.9.15/common/mercury_cli.c)

Configure `mercury.host`, `mercury.port` and `mercury.mode_index` in
`il2p_gateway.yaml` to match the running Mercury process. The upstream
broadcast port defaults to **8100** (`-b` overrides it). Mode index defaults
to **1 / DATAC3** upstream. This KISS interface cannot query or change the
actual modem mode; the configured mode is a capacity assumption, not telemetry.

Select `transport.mode: mercury_broadcast`, `coding: profile` (or `none`).
Use `tx: false` for encode-only preview; `tx: true` queues data for radio TX.
The existing fldigi profile remains the default. For receive-only operation,
POST `/watch/start` with `{"mode":"mercury_broadcast"}` and poll
`/rx/results`. `/watch/stop` releases the broadcast socket. Status reads do
not connect or send probes. Loading configuration does not start a watcher.

The TCP packet is `C0 02 <escaped binary IL2P> C0`: `C0` becomes `DB DC`
and `DB` becomes `DB DD`. No Base32/Base64 or text tags are sent to Mercury.
The Base64 field in REST responses is only a binary preview. Command `02`
means an unformatted message; Mercury adds its own one-byte header and
two-byte length prefix for RF, then removes these and padding before RX
delivery. Command `03` means a prebuilt **Mercury modem frame**, so it is
unsuitable for a bare IL2P frame.

The complete IL2P frame must fit `modem_frame_bytes - 3` (e.g. DATAC3:
123 bytes; DATAC1: 507 bytes). Oversize TX is rejected before connecting,
because upstream can silently truncate messages. There is no fragmentation.
Update the gateway's mode index whenever Mercury's external mode changes.

Mercury accepts one broadcast client at a time; disconnect other broadcast
clients before using the gateway. REST TX and the binary watcher reuse one
socket and retain partial/concatenated KISS frames across polls. Invalid
escapes/oversize RX frames produce consumed errors and subsequent frames
remain readable. Only command `02` on KISS port 0 is treated as IL2P;
other data commands produce errors, control commands/other ports are ignored.
Legacy unwrapped Mercury/RaptorQ modem frames are not decoded by this backend.

Successful `send()` means TCP queueing, not RF completion or remote delivery.
Failed writes are never automatically replayed. RX reconnects on subsequent
polls after disconnect, discarding old partial transport data. No application
ACK/retry or Mercury ARQ is implemented; APRS ACK remains an application payload.
Unknown SNR/bitrate/TRX metrics stay unknown. The fldigi text watcher remains
in use for its SNR samples, candidate timeouts and malformed text results.
