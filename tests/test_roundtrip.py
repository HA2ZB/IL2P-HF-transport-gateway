from il2p.codec import decode_il2p_frame, encode_il2p_type1_ui, rebuild_ax25_ui_frame


def run_case(payload: bytes, fec: int) -> None:
    ax25_original, _raw_hdr, _full_hdr, _enc_payload, il2p_full = encode_il2p_type1_ui(
        "HA2ZB-0", "APIL2P-0", payload, fec
    )
    decoded = decode_il2p_frame(il2p_full)
    assert rebuild_ax25_ui_frame(decoded) == ax25_original


def test_short_fec0():
    run_case(b"=4739.97N/01938.97E-IL2P-TEST", 0)


def test_short_fec1():
    run_case(b"=4739.97N/01938.97E-IL2P-TEST", 1)


def test_long_fec0():
    run_case(b"=" + b"X" * 300, 0)


def test_long_fec1():
    run_case(b"=" + b"X" * 300, 1)
