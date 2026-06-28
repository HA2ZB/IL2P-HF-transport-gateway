from il2p.framing import decode_frame_text, encode_frame_text


def test_base64_frame_roundtrip():
    data = bytes(range(64))
    text = encode_frame_text(data, coding="base64")
    assert decode_frame_text(text) == data


def test_base32_frame_roundtrip():
    data = bytes(range(64))
    text = encode_frame_text(data, coding="base32")
    assert decode_frame_text(text) == data


def test_canonical_human_readable_frame_has_callsign_and_len():
    data = b"abc123"
    text = encode_frame_text(data, coding="base64", callsign="HA2ZB")
    assert text.startswith("HA2ZB IL2P CODING=BASE64 LEN=6 <IL2P>")
    assert decode_frame_text(text) == data


def test_legacy_coding_dash_is_accepted():
    data = b"abc123"
    text = encode_frame_text(data, coding="base32", callsign="HA2ZB").replace("CODING=BASE32", "CODING-BASE32")
    assert decode_frame_text(text) == data
