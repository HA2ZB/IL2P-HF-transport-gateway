
# IL2P HF Gateway REST API

**Version:** Draft 1  
**Status:** Sprint 2

---

# Introduction

The IL2P HF Gateway exposes a lightweight REST API that allows external applications to send APRS messages, monitor gateway status and retrieve received frames.

All requests and responses use JSON.

---

# Starting the Service

```bash
python -m pip install -r requirements.txt
python IL2P_rest_service.py --config il2p_gateway.yaml
```

Default endpoint:

```
http://localhost:8000
```

---

# Typical Workflow

1. GET /status
2. POST /message
3. Wait until the gateway returns to IDLE
4. GET /rx/results

---

# GET /status

Returns the current gateway state.

## Request

```http
GET /status
```

## Example Response

```json
{
  "state":"IDLE",
  "rx_active":true,
  "tx_active":false,
  "last_result_id":12
}
```

Field | Description
----- | -----------
state | Current link state
rx_active | Receiver running
tx_active | Transmission active
last_result_id | Latest receive result

Possible states:

- IDLE
- TX_PREPARE
- TX_ACTIVE
- RX_RESYNC
- RX_ACTIVE
- ERROR

---

# POST /message

Queues an APRS message for transmission.

```json
{
  "to":"HA5XYZ",
  "text":"Hello World",
  "transport":{
    "mode":"olivia_4_250"
  }
}
```

Successful response:

```json
{
  "queued":true,
  "message_id":27
}
```

The gateway automatically configures the modem, performs IL2P encoding and starts transmission.

---

# GET /rx/results

Returns decoded receive results.

```
GET /rx/results
```

Only newer results:

```
GET /rx/results?since=12
```

---

# GET /rx/results/{id}

Returns one receive result.

Example:

```json
{
  "id":27,
  "valid":true,
  "from":"HA2ZB",
  "to":"HA5XYZ",
  "payload":"Hello World"
}
```

Result IDs are internal REST identifiers and are not part of the IL2P protocol.

---

# Error Codes

| HTTP | Description |
|------|-------------|
|200|Success|
|202|Accepted|
|400|Invalid request|
|404|Unknown endpoint|
|409|Link busy|
|500|Internal error|
|503|Modem unavailable|

---

# Mode Profiles

Applications never configure the modem directly.

Instead they select a Mode Profile.

Example:

```json
{
  "transport":{
    "mode":"contestia_4_250"
  }
}
```

The profile determines:

- modem backend
- digital mode
- coding
- FEC
- TXID/RXID policy

---

# Design Philosophy

The REST API hides the complexity of the radio link.

Applications communicate only through JSON while the gateway manages:

- IL2P encoding
- modem configuration
- half-duplex state machine
- receive recovery

---

# Future Extensions

Planned additions include:

- diagnostics
- statistics
- modem management
- WebSocket notifications
- authentication
- OpenAPI specification
