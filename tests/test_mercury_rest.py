import socket
import time

import pytest
from fastapi.testclient import TestClient

from il2p.api import rest
from il2p.codec import decode_il2p_frame, encode_il2p_type1_ui
from il2p.modem.kiss import KissDecoder, encode_kiss


@pytest.fixture(autouse=True)
def config(monkeypatch):
    old_config = rest.state.config
    rest.state.config = {
        "gateway": {"callsign": "HA2ZB-0"},
        "transport_defaults": {"mode": "mercury_broadcast", "coding": "profile", "tx": False},
        "mercury": {"host": "127.0.0.1", "mode_index": 0},
        "mode_profiles": {"mercury_broadcast": {"adapter": "mercury", "default_coding": "none"}},
    }
    rest.state.rx_store.results.clear()
    rest.state.rx_store.next_result_id = 1
    rest.state.tx_log.clear()
    monkeypatch.setattr(rest, "fldigi_status", lambda: {})
    yield
    if rest.state.watcher_service:
        rest.rx_watch_stop()
    if rest.state.mercury_modem:
        rest.state.mercury_modem.close()
    rest.state.mercury_modem = None
    rest.state.config = old_config


def test_mercury_encode_only_and_status_never_connect(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *a: pytest.fail("Unexpected TCP connect"))
    client = TestClient(rest.app)
    response = client.post("/send", json={"payload": "preview"})
    assert response.status_code == 200
    assert response.json()["tx"]["coding"] == "none"
    assert response.json()["framed_text"] == ""
    assert client.get("/status").json()["mercury"]["state"] == "disconnected"


@pytest.mark.parametrize("coding", ["base32", "base64"])
def test_mercury_rejects_text_coding_even_for_preview(coding):
    response = TestClient(rest.app).post("/send", json={
        "payload": "preview", "transport": {"coding": coding},
    })
    assert response.status_code == 400


def test_rest_mercury_tx_is_raw_il2p(monkeypatch):
    captured = []
    class Modem:
        def send(self, data, options):
            captured.append((data, options))
    monkeypatch.setattr(rest, "mercury_modem", lambda: Modem())
    response = TestClient(rest.app).post("/send/aprs", json={
        "to": "HA5XYZ", "text": "ack1", "transport": {"tx": True},
    })
    assert response.status_code == 200
    data, options = captured[0]
    assert decode_il2p_frame(data)["aprs_text"].endswith(":ack1")
    assert options.coding == "none"
    assert data == bytes.fromhex(response.json()["il2p"]["hex"])


def test_rest_oversize_rejected_before_socket_connect(monkeypatch):
    rest.state.config["mercury"]["mode_index"] = 1
    monkeypatch.setattr(socket, "create_connection", lambda *a: pytest.fail("Oversize TX connected"))
    response = TestClient(rest.app).post("/send", json={
        "payload": "x" * 130, "transport": {"tx": True},
    })
    assert response.status_code == 400
    assert "123" in response.json()["detail"]


def test_rest_watcher_and_tx_share_one_loopback_connection():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    rest.state.config["mercury"]["port"] = listener.getsockname()[1]
    client = TestClient(rest.app)
    peer = None
    try:
        assert client.post("/watch/start", json={"poll_s": 0.01}).status_code == 200
        peer, _ = listener.accept()
        peer.settimeout(2)
        # Starting RX opens TCP but sends no data.
        peer.settimeout(0.02)
        with pytest.raises(socket.timeout):
            peer.recv(1)
        peer.settimeout(2)
        frame = encode_il2p_type1_ui("HA2ZB-0", "APIL2P-0", b":HA5XYZ   :ack1", 1)[-1]
        peer.sendall(encode_kiss(frame))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and rest.state.rx_store.last_result_id == 0:
            time.sleep(0.01)
        results = client.get("/rx/results").json()["items"]
        assert results[0]["valid"] and results[0]["coding"] == "none"
        assert results[0]["aprs_text"].endswith(":ack1")
        cached = rest.state.mercury_modem
        assert client.post("/send", json={"payload": "TX", "transport": {"tx": True}}).status_code == 200
        assert rest.state.mercury_modem is cached
        decoder = KissDecoder()
        frames = []
        while not frames:
            frames.extend(decoder.feed(peer.recv(4096)))
        assert frames[0][0] == 2
        assert decode_il2p_frame(frames[0][1])["aprs_text"] == "TX"
        assert client.post("/watch/pause").json()["paused"]
        assert not client.post("/watch/resume").json()["paused"]
        assert client.post("/watch/stop").status_code == 200
        assert peer.recv(1) == b""
    finally:
        if rest.state.watcher_service:
            rest.rx_watch_stop()
        if peer:
            peer.close()
        listener.close()


def test_connection_settings_change_closes_old_socket():
    first = rest.mercury_modem()
    rest.state.config["mercury"]["mode_index"] = 1
    second = rest.mercury_modem()
    assert first is not second
    assert second.max_payload_bytes == 123


def test_application_shutdown_releases_tx_only_socket():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    rest.state.config["mercury"]["port"] = listener.getsockname()[1]
    peer = None
    try:
        with TestClient(rest.app) as client:
            assert client.post("/send", json={"payload": "TX", "transport": {"tx": True}}).status_code == 200
            peer, _ = listener.accept()
            peer.settimeout(2)
            decoder = KissDecoder()
            frames = []
            while not frames:
                frames.extend(decoder.feed(peer.recv(4096)))
        assert peer.recv(1) == b""
        assert rest.state.mercury_modem.status().state == "disconnected"
    finally:
        if peer:
            peer.close()
        listener.close()
