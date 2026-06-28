#!/usr/bin/env python3
from tools.il2p_encode import main
from il2p.codec import encode_il2p_type1_ui
from il2p.codec.ax25 import build_ax25_ui_frame, encode_ax25_addr, parse_callsign
from il2p.codec.il2p_type1 import make_il2p_header, split_payload_blocks

if __name__ == "__main__":
    main()
