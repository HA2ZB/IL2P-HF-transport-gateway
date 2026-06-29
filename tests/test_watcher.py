from il2p.codec import encode_il2p_type1_ui
from il2p.framing import encode_frame_text
from il2p.runtime import LinkState, RxStore, RxWatcher, parse_freq_offset_hz, parse_snr_db


def _frame(coding="base64"):
    _ax25, _raw_hdr, _full_hdr, _enc_payload, il2p = encode_il2p_type1_ui(
        "HA2ZB-0", "APIL2P-0", b"=4739.97N/01938.97E-IL2P-TEST", 1
    )
    return encode_frame_text(il2p, coding=coding, callsign="HA2ZB")


def test_watcher_decodes_valid_base64_frame_into_rx_store():
    store = RxStore()
    watcher = RxWatcher(store, mode="OLIVIA-4-250")
    watcher.update_status(status1="s/n: -3.5 dB", status2="f/o -31.2 Hz")

    ids = watcher.feed(_frame("base64"))

    assert ids == [1]
    assert store.last_result_id == 1
    result = store.get_result(1)
    assert result is not None
    assert result.valid is True
    assert result.mode == "OLIVIA-4-250"
    assert result.src == "HA2ZB-0"
    assert result.dst == "APIL2P-0"
    assert result.aprs_text == "=4739.97N/01938.97E-IL2P-TEST"
    assert result.diagnostics.snr_last == -3.5
    assert result.diagnostics.freq_offset_last_hz == -31.2


def test_watcher_ignores_incomplete_frame_until_end_tag_arrives():
    store = RxStore()
    watcher = RxWatcher(store)
    text = _frame("base32")
    cut = text.index("</IL2P>")

    assert watcher.feed(text[:cut]) == []
    assert store.last_result_id == 0
    assert store.state == LinkState.FRAME_CANDIDATE

    ids = watcher.feed(text[cut:])
    assert ids == [1]
    assert store.get_result(1).valid is True


def test_watcher_records_invalid_complete_candidate():
    store = RxStore()
    watcher = RxWatcher(store)

    ids = watcher.feed("HA2ZB IL2P CODING=BASE64 LEN=3 <IL2P>AAAA</IL2P>")

    assert ids == [1]
    result = store.get_result(1)
    assert result.valid is False
    assert result.reason


def test_status_parsers():
    assert parse_snr_db("s/n:  3.1 dB") == 3.1
    assert parse_snr_db("S/N: -9.4 dB") == -9.4
    assert parse_freq_offset_hz("f/o -31.2 Hz") == -31.2


def test_watcher_candidate_timeout_returns_to_rx_noise_without_result(monkeypatch):
    store = RxStore()
    watcher = RxWatcher(store, candidate_timeout_s=5.0)

    times = iter([1000.0, 1006.0])
    monkeypatch.setattr("il2p.runtime.watcher.time.time", lambda: next(times))

    assert watcher.feed("HA2ZB IL2P CODING=BASE64 LEN=99 <IL2P>PARTIAL") == []
    assert store.state == LinkState.FRAME_CANDIDATE
    watcher.tick()

    assert store.state == LinkState.RX_NOISE
    assert store.last_result_id == 0
    assert watcher.frame_active is False


def test_valid_frame_is_rx_result_not_persistent_link_state():
    store = RxStore()
    watcher = RxWatcher(store)

    ids = watcher.feed(_frame("base64"))

    assert ids == [1]
    assert store.get_result(1).valid is True
    assert store.state == LinkState.RX_NOISE
