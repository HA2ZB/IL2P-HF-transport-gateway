from IL2P_encoder_block import encode_il2p_type1_ui
from IL2P_decoder_block import decode_il2p_frame, rebuild_ax25_ui_frame


def run_roundtrip_test(name: str, payload: bytes, fec: int) -> None:
    print()
    print(name)

    ax25_original, raw_hdr, full_hdr, enc_payload, il2p_full = encode_il2p_type1_ui(
        "HA2ZB-0",
        "APIL2P-0",
        payload,
        fec,
    )

    decoded = decode_il2p_frame(il2p_full)
    ax25_rebuilt = rebuild_ax25_ui_frame(decoded)

    print("FEC:", fec)
    print("PAYLOAD_LEN:", len(payload))
    print("IL2P_LEN:", len(il2p_full))
    print("AX25_MATCH:", ax25_rebuilt == ax25_original)

    if ax25_rebuilt != ax25_original:
        raise RuntimeError("AX.25 roundtrip mismatch")


if __name__ == "__main__":
    print("IL2P ENCODE/DECODE ROUNDTRIP TEST")

    run_roundtrip_test(
        "SHORT PAYLOAD / FEC0",
        b"=4739.97N/01938.97E-IL2P-TEST",
        0,
    )

    run_roundtrip_test(
        "SHORT PAYLOAD / FEC1",
        b"=4739.97N/01938.97E-IL2P-TEST",
        1,
    )

    run_roundtrip_test(
        "LONG PAYLOAD / FEC0",
        b"=" + b"X" * 300,
        0,
    )

    run_roundtrip_test(
        "LONG PAYLOAD / FEC1",
        b"=" + b"X" * 300,
        1,
    )

    print()
    print("ALL ROUNDTRIP TESTS PASSED")