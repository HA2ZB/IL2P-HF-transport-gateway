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
