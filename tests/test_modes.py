from il2p.config import profile_from_config


def test_olivia_profile_defaults_to_base64_and_txid_only():
    p = profile_from_config("olivia_4_250", {
        "adapter": "fldigi",
        "fldigi_mode": "Olivia 4/250",
        "default_coding": "base64",
        "announce_mode": True,
        "auto_detect_mode": False,
    })
    assert p.adapter == "fldigi"
    assert p.fldigi_mode == "Olivia 4/250"
    assert p.default_coding == "base64"
    assert p.announce_mode is True
    assert p.auto_detect_mode is False


def test_legacy_profile_keys_still_work():
    p = profile_from_config("contestia_4_250", {
        "modem": "fldigi",
        "fldigi_mode_hint": "Contestia 4/250",
        "coding": "base32",
        "txid": True,
        "rxid": False,
    })
    assert p.adapter == "fldigi"
    assert p.fldigi_mode == "Contestia 4/250"
    assert p.default_coding == "base32"
