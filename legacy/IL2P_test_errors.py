from IL2P_encoder_block import encode_il2p_type1_ui
from IL2P_decoder_block import decode_il2p_frame, rebuild_ax25_ui_frame


SRC = "HA2ZB-0"
DST = "APIL2P-0"
PAYLOAD = b"=" + b"X" * 300
FEC = 1


def run_test(name: str, corrupted_indexes: list[int]) -> None:
    print()
    print(name)
    print("CORRUPTED_BYTE_INDEXES:", corrupted_indexes)

    ax25_original, raw_hdr, full_hdr, enc_payload, il2p_full = encode_il2p_type1_ui(
        SRC,
        DST,
        PAYLOAD,
        FEC,
    )

    corrupted = bytearray(il2p_full)

    for i in corrupted_indexes:
        corrupted[i] ^= 0x55

    try:
        decoded = decode_il2p_frame(bytes(corrupted))
        ax25 = rebuild_ax25_ui_frame(decoded)

        print("DECODE_OK:", True)
        print("AX25_MATCH_AFTER_REPAIR:", ax25 == ax25_original)
        print("APRS_LEN:", len(decoded["payload_raw"]))

    except ValueError as e:
        print("DECODE_OK:", False)
        print("REPAIR_FAILED:", e)


if __name__ == "__main__":
    print("IL2P AUTOMATIC MULTI-BLOCK ERROR CORRECTION TEST")

    run_test(
        "BLOCK 1 / 8 BYTE ERROR / SHOULD REPAIR",
        [20, 21, 22, 23, 24, 25, 26, 27],
    )

    run_test(
        "BLOCK 1 / 9 BYTE ERROR / SHOULD FAIL",
        [20, 21, 22, 23, 24, 25, 26, 27, 28],
    )

    run_test(
        "BLOCK 2 / 8 BYTE ERROR / SHOULD REPAIR",
        [270, 271, 272, 273, 274, 275, 276, 277],
    )

    run_test(
        "BLOCK 2 / 9 BYTE ERROR / SHOULD FAIL",
        [270, 271, 272, 273, 274, 275, 276, 277, 278],
    )

    run_test(
        "BLOCK 1 + BLOCK 2 / 8+8 BYTE ERROR / SHOULD REPAIR",
        [
            20, 21, 22, 23, 24, 25, 26, 27,
            270, 271, 272, 273, 274, 275, 276, 277,
        ],
    )