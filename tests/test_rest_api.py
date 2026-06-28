from fastapi.testclient import TestClient

from il2p.api.rest import app, state


BASE_CONFIG = {
    "gateway": {"callsign": "HA2ZB-0"},
    "aprs": {"default_il2p_destination": "APIL2P-0"},
    "transport_defaults": {"mode": "olivia_4_250", "coding": "profile", "tx": False},
    "mode_profiles": {
        "olivia_4_250": {
            "adapter": "fldigi",
            "fldigi_mode": "Olivia 4/250",
            "default_coding": "base64",
            "default_fec": 1,
            "announce_mode": True,
            "auto_detect_mode": False,
        }
    },
}


def setup_function():
    state.config = {k: (v.copy() if isinstance(v, dict) else v) for k, v in BASE_CONFIG.items()}
    state.tx_log.clear()
    state.rx_store.results.clear()
    state.rx_store.next_result_id = 1


def test_modes_endpoint_exposes_frozen_public_name():
    client = TestClient(app)
    res = client.get("/modes")
    assert res.status_code == 200
    data = res.json()
    assert data["default"] == "olivia_4_250"
    assert data["modes"]["olivia_4_250"]["default_coding"] == "base64"


def test_generic_send_is_not_aprs_specific_and_can_encode_only():
    client = TestClient(app)
    res = client.post("/send", json={
        "payload": "Hello transport",
        "transport": {"mode": "olivia_4_250", "tx": False},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["normalized"]["application"] == "generic"
    assert data["normalized"]["payload"] == "Hello transport"
    assert data["tx"]["tx_requested"] is False
    assert data["framed_text"].startswith("HA2ZB IL2P CODING=BASE64 LEN=")


def test_send_aprs_builds_aprs_message_payload():
    client = TestClient(app)
    res = client.post("/send/aprs", json={
        "to": "HA5XYZ",
        "text": "Hello APRS",
        "transport": {"mode": "olivia_4_250", "tx": False},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["normalized"]["application"] == "aprs"
    assert data["normalized"]["aprs_info"].startswith(":HA5XYZ")


def test_statistics_endpoint_counts_rx_results():
    state.rx_store.append_result(valid=True)
    state.rx_store.append_result(valid=False, reason="bad frame")
    client = TestClient(app)
    res = client.get("/statistics")
    assert res.status_code == 200
    data = res.json()
    assert data["frames_ok"] == 1
    assert data["frames_bad"] == 1
    assert data["last_result_id"] == 2
