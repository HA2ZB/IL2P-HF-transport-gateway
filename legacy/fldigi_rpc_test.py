# File: fldigi_rpc_test.py
#
# Minimal fldigi XML-RPC interface test
#
# Requirements:
#   pip install requests
#
# fldigi:
#   Configure -> Misc -> XML-RPC
#   Enable XML-RPC server
#
# Default:
#   http://127.0.0.1:7362
#
# Usage:
#
#   python fldigi_rpc_test.py info
#
#   python fldigi_rpc_test.py tx "HELLO WORLD"
#
#   python fldigi_rpc_test.py rx
#

import argparse
import sys
import time
import xmlrpc.client

from pathlib import Path


FLDIGI_URL = "http://127.0.0.1:7362"


# ============================================================
# Connection
# ============================================================

def connect():
    return xmlrpc.client.ServerProxy(FLDIGI_URL)


# ============================================================
# Helpers
# ============================================================

def print_status(fldigi):
    try:
        name = fldigi.main.get_wfcarrier()
    except Exception:
        name = "N/A"

    try:
        modem = fldigi.modem.get_name()
    except Exception:
        modem = "UNKNOWN"

    try:
        trx = fldigi.main.get_trx_state()
    except Exception:
        trx = "?"

    print("FLDIGI XML-RPC CONNECTED")
    print("MODEM =", modem)
    print("TRX   =", trx)
    print("CARR  =", name)
    
    print()
    print("XML-RPC METHODS:")
    methods = fldigi.system.listMethods()

    for m in sorted(methods):
        print(m)


# ============================================================
# TX
# ============================================================

def tx_text(fldigi, text):
    print("CLEAR TX BUFFER")
    fldigi.text.clear_tx()

    print("QUEUE TEXT")
    fldigi.text.add_tx(text)

    print("START TX")
    fldigi.main.tx()

    print("TX STARTED")
    print("Do not switch to RX until fldigi has sent the full frame.")



# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Minimal fldigi XML-RPC test tool"
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info")

    txp = sub.add_parser("tx")
    txp.add_argument("text")

    txfile = sub.add_parser("txfile")
    txfile.add_argument("file")

    args = parser.parse_args()

    try:
        fldigi = connect()

        # test connectivity
        fldigi.main.get_trx_state()

    except Exception as e:
        print(f"ERROR: fldigi XML-RPC connection failed: {e}")
        print("Check:")
        print("  fldigi running")
        print("  XML-RPC enabled")
        print("  port 7362")
        return 1

    if args.cmd == "info":
        print_status(fldigi)
        return 0

    if args.cmd == "tx":
        tx_text(fldigi, args.text)
        return 0

    if args.cmd == "rx":
        read_rx(fldigi)
        return 0
        
    if args.cmd == "txfile":
        text = Path(args.file).read_text(encoding="ascii", errors="ignore")
        text = text.replace("\r", "").replace("\n", "")
        tx_text(fldigi, text)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())