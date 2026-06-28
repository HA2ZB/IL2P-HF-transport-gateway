#!/usr/bin/env python3
from tools.il2p_decode import main
from il2p.codec import decode_il2p_frame, rebuild_ax25_ui_frame
from il2p.codec.il2p_type1 import parse_il2p_header, split_payload_blocks

if __name__ == "__main__":
    main()
