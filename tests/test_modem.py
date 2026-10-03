import xmlrpc.client

import pytest

from il2p.framing import encode_frame_text
from il2p.modem import FldigiXmlRpcModem, TxOptions


@pytest.mark.parametrize("coding", ["base32", "base64"])
def test_send_uses_existing_wire_format(coding):
    modem = FldigiXmlRpcModem()
    sent = []
    modem.tx_text = lambda text, options: sent.append(text)
    data = bytes(range(256))
    modem.send(data, TxOptions(coding=coding, callsign="HA2ZB"))
    assert sent == [encode_frame_text(data, coding=coding, callsign="HA2ZB")]


def test_receive_preserves_partial_next_frame_and_repeated_packets():
    modem = FldigiXmlRpcModem()
    frame = encode_frame_text(b"packet")
    chunks = iter([frame[:15], frame[15:] + frame[:20], frame[20:]])
    modem.rx_text = lambda: next(chunks)
    assert modem.receive() == b""
    assert modem.receive() == b"packet"
    assert modem.receive() == b"packet"


def test_receive_bad_transport_frame_does_not_drop_next_packet():
    modem = FldigiXmlRpcModem()
    modem.rx_text = lambda: "IL2P CODING=BASE64 LEN=99 <IL2P>AAAA</IL2P>" + encode_frame_text(b"good")
    with pytest.raises(ValueError):
        modem.receive()
    assert modem.receive() == b"good"


def test_send_rejects_raw_coding_before_rpc():
    with pytest.raises(ValueError):
        FldigiXmlRpcModem().send(b"raw", TxOptions(coding="none"))


def test_rx_accepts_xmlrpc_binary():
    modem = FldigiXmlRpcModem()
    class Rx:
        def get_data(self):
            return xmlrpc.client.Binary(b"text")
    class Rpc:
        rx = Rx()
    modem.rpc = Rpc()
    assert modem.rx_text() == "text"


def test_receive_ignores_stray_end_tag_in_noise():
    modem = FldigiXmlRpcModem()
    chunks = iter(["noise </IL2P> " + encode_frame_text(b"first"), encode_frame_text(b"second")])
    modem.rx_text = lambda: next(chunks)
    assert modem.receive() == b"first"
    assert modem.receive() == b"second"
