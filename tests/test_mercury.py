from collections import deque
import socket
import time

import pytest

from il2p.codec import decode_il2p_frame, encode_il2p_type1_ui
from il2p.modem import MercuryKissTcpModem, TxOptions
from il2p.modem.kiss import KissDecoder, encode_kiss
from il2p.runtime import PacketRxWatcher, PacketWatcherService, RxStore


def il2p_frame():
    return encode_il2p_type1_ui("HA2ZB-0", "APIL2P-0", b":HA5XYZ   :Hello{1", 1)[-1]


@pytest.mark.parametrize("cut", range(1, 11))
def test_kiss_partial_and_concatenated_frames(cut):
    first = encode_kiss(b"\x00\xc0\xdb\xff")
    decoder = KissDecoder()
    results = decoder.feed(b"noise\xc0" + first[:cut])
    results += decoder.feed(first[cut:] + encode_kiss(b"next"))
    assert results == [(2, b"\x00\xc0\xdb\xff"), (2, b"next")]


def test_kiss_every_byte_and_shared_delimiter():
    payload = bytes(range(256))
    decoder = KissDecoder()
    results = []
    for byte in encode_kiss(payload) + encode_kiss(b"\x00\x00")[1:]:
        results.extend(decoder.feed(bytes([byte])))
    assert results == [(2, payload), (2, b"\x00\x00")]


@pytest.mark.parametrize("bad", [b"\xc0\x02\xdb\x01\xc0", b"\xc0\x02\xdb\xc0",
                                 encode_kiss(b"12345")])
def test_kiss_error_is_consumed_and_next_frame_survives(bad):
    decoder = KissDecoder(max_payload=4)
    results = decoder.feed(bad + encode_kiss(b"good"))
    assert isinstance(results[0], ValueError)
    assert results[1] == (2, b"good")


@pytest.fixture
def tcp_pair():
    # Real loopback TCP only, never an installed Mercury process.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    modem = MercuryKissTcpModem("127.0.0.1", listener.getsockname()[1], mode_index=0)
    modem.connect()
    peer, _ = listener.accept()
    peer.settimeout(2)
    try:
        yield modem, peer, listener
    finally:
        modem.close()
        peer.close()
        listener.close()


def receive_eventually(modem):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        data = modem.receive()
        if data:
            return data
        time.sleep(0.001)
    pytest.fail("No TCP test frame received")


def test_tcp_binary_send_and_receive_keeps_socket_and_partial_data(tcp_pair):
    modem, peer, _ = tcp_pair
    frame = il2p_frame()
    modem.send(frame, TxOptions(coding="none"))
    decoder = KissDecoder()
    results = []
    while not results:
        results.extend(decoder.feed(peer.recv(4096)))
    assert results == [(2, frame)]
    packet = encode_kiss(frame)
    peer.sendall(packet[:4])
    assert modem.receive() == b""
    peer.sendall(packet[4:] + encode_kiss(b"\xc0\xdb\x00"))
    assert receive_eventually(modem) == frame
    assert receive_eventually(modem) == b"\xc0\xdb\x00"
    assert modem.receive() == b""
    assert decode_il2p_frame(frame)["aprs_text"] == ":HA5XYZ   :Hello{1"


def test_tcp_disconnect_discards_partial_frame_and_can_reconnect(tcp_pair):
    modem, peer, listener = tcp_pair
    peer.sendall(b"\xc0\x02partial")
    modem.receive()
    peer.shutdown(socket.SHUT_RDWR)
    peer.close()
    deadline = time.monotonic() + 2
    while True:
        try:
            modem.receive()
        except ConnectionError:
            break
        assert time.monotonic() < deadline
        time.sleep(0.001)
    assert modem.status().state == "disconnected"
    modem.connect()
    new_peer, _ = listener.accept()
    try:
        new_peer.sendall(encode_kiss(b"new\x00"))
        assert receive_eventually(modem) == b"new\x00"
    finally:
        new_peer.close()


def test_tcp_rejects_other_data_commands_but_keeps_later_data(tcp_pair):
    modem, peer, _ = tcp_pair
    peer.sendall(encode_kiss(b"control", 6) + encode_kiss(b"other port", 0x12)
                 + encode_kiss(b"raw modem", 3) + encode_kiss(b"valid"))
    deadline = time.monotonic() + 2
    with pytest.raises(ValueError, match="command"):
        while time.monotonic() < deadline:
            modem.receive()
            time.sleep(0.001)
    assert receive_eventually(modem) == b"valid"


def test_send_capacity_and_options_fail_before_connect(monkeypatch):
    modem = MercuryKissTcpModem(mode_index=1)
    monkeypatch.setattr(socket, "create_connection", lambda *a: pytest.fail("Unexpected connect"))
    for data in (b"", b"x" * 124):
        with pytest.raises(ValueError, match="1..123"):
            modem.send(data)
    with pytest.raises(ValueError, match="coding"):
        modem.send(b"x", TxOptions(coding="base64"))
    with pytest.raises(NotImplementedError):
        modem.set_mode("DATAC1")
    assert modem.status().snr_db is None
    assert modem.status().mode is None


def test_failed_write_is_not_replayed(monkeypatch):
    modem = MercuryKissTcpModem()
    class FailedSocket:
        writes = 0
        closed = False
        def sendall(self, data):
            self.writes += 1
            raise OSError("partial write")
        def close(self):
            self.closed = True
    sock = FailedSocket()
    modem._socket = sock
    monkeypatch.setattr(socket, "create_connection", lambda *a: pytest.fail("TX replay"))
    with pytest.raises(OSError):
        modem.send(b"data")
    assert sock.closed and sock.writes == 1
    assert modem.status().state == "disconnected"


def test_send_accepts_exact_capacity(tcp_pair):
    modem, peer, _ = tcp_pair
    payload = b"\xc0" * 507
    modem.send(payload)
    decoder = KissDecoder()
    frames = []
    while not frames:
        frames.extend(decoder.feed(peer.recv(4096)))
    assert frames == [(2, payload)]
    with pytest.raises(ValueError):
        modem.send(payload + b"\x00")


def test_binary_watcher_records_transport_and_il2p_errors_then_valid_frame():
    frames = deque([ValueError("bad escape"), b"invalid IL2P", il2p_frame(), b""])
    class Source:
        def receive(self):
            item = frames.popleft()
            if isinstance(item, Exception):
                raise item
            return item
    store = RxStore()
    watcher = PacketRxWatcher(store, mode="mercury_broadcast")
    service = PacketWatcherService(Source(), watcher)
    for _ in range(4):
        service.poll_once()
    results = store.list_results(detailed=True)
    assert [r["valid"] for r in results] == [False, False, True]
    assert results[-1]["coding"] == "none"
    assert results[-1]["aprs_text"].endswith("Hello{1")
    assert results[-1]["diagnostics"]["snr_avg"] is None
    assert watcher.stats.valid_frames == 1
    assert watcher.stats.invalid_frames == 2
