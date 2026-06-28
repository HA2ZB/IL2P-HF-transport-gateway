# IL2P HF Gateway

> **Open-source HF transport for APRS messaging using IL2P over modern
> narrow-band digital modes.**

------------------------------------------------------------------------

## Overview

**IL2P HF Gateway** is an experimental implementation of an HF messaging
gateway based on the open **IL2P** protocol.

The project combines:

-   **IL2P** as the Layer-2 data link protocol
-   **fldigi** as the initial modem backend
-   Modern HF digital modes such as **Olivia** and **Contestia**
-   A REST API for external applications
-   Human-readable over-the-air framing for transparency and
    interoperability

Unlike proprietary solutions, the entire protocol stack is designed to
remain open, inspectable and community-extensible.

------------------------------------------------------------------------

## Project Goals

-   Fully open HF transport
-   Native IL2P implementation
-   APRS-compatible information payloads
-   Transparent HF gateway architecture
-   Modular modem abstraction
-   REST API for automation
-   Future support for additional modem engines (VARA, ARDOP, etc.)

------------------------------------------------------------------------

# Sprint 2

Sprint 2 introduces the first version of the application layer on top of
the modular architecture created during Sprint 1.

## Highlights

-   Mode Profile abstraction
-   Automatic fldigi mode switching
-   Half-duplex TX/RX state machine
-   REST polling model
-   Human-readable on-air framing
-   Canonical text framing (Base32/Base64)
-   Runtime RX result queue

------------------------------------------------------------------------

## Architecture

``` text
il2p/
├── codec/          IL2P codec, AX.25 helpers, Reed-Solomon, scrambler
├── framing/        Base32/Base64 framing
├── modem/          fldigi XML-RPC modem adapter
├── config/         Mode profile configuration
├── runtime/        Link state and RX queue
├── aprs/           APRS helpers
├── diagnostics/    SNR/statistics
└── api/            REST API

tools/
legacy/
```

------------------------------------------------------------------------

## Mode Profiles

Rather than selecting modem parameters individually, applications simply
request a **mode profile**.

Example:

``` yaml
mode_profiles:
  olivia_4_250:
    adapter: fldigi
    fldigi_mode: Olivia 4/250
    default_coding: base64
    default_fec: 1
    announce_mode: true
    auto_detect_mode: false
    keep_human_readable_frame: true
```

The profile determines:

-   modem backend
-   modulation
-   coding
-   FEC
-   TXID/RXID policy

------------------------------------------------------------------------

## Human-readable frame

``` text
HA2ZB IL2P CODING=BASE64 LEN=69 <IL2P>...</IL2P>
```

The project intentionally keeps the transmitted frame understandable for
both operators and third parties.

------------------------------------------------------------------------

## REST API

### Installation

``` bash
python -m pip install -r requirements.txt
```

### Start

``` bash
python IL2P_rest_service.py --config il2p_gateway.yaml
```

### Status

``` http
GET /status
```

### Send APRS message

``` json
POST /message
{
  "to":"HA5XYZ",
  "text":"Hello",
  "transport":{
      "mode":"olivia_4_250"
  }
}
```

### Encode only

``` json
POST /message
{
  "to":"HA5XYZ",
  "text":"Hello",
  "transport":{
      "mode":"contestia_4_250",
      "tx":false
  }
}
```

### Poll RX results

``` http
GET /rx/results
GET /rx/results/{id}
```

See `rest_api.md` for details.

------------------------------------------------------------------------

## CLI Examples

``` bash
python tools/il2p_encode.py ...
python tools/il2p_decode.py ...
python tools/il2p_frame.py encode ...
python tools/il2p_frame.py decode ...
```

------------------------------------------------------------------------

## Testing

``` bash
python -m pytest
```

Using `python -m pytest` is recommended, particularly on Microsoft Store
Python installations.

------------------------------------------------------------------------

## Current Status

### Completed

-   IL2P encoder
-   IL2P decoder
-   AX.25 compatibility
-   Reed-Solomon FEC
-   Base32/Base64 framing
-   REST service skeleton
-   Mode profile abstraction
-   fldigi integration

### Planned

-   Background RX watcher
-   Automatic frame dispatch
-   Additional modem adapters
-   Gateway routing
-   APRS network integration
-   Extended diagnostics

------------------------------------------------------------------------

## License

This project is licensed under the **GNU General Public License v2.0 or 
later (GPL-2.0-or-later)**.

See the `LICENSE` file for details.

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
