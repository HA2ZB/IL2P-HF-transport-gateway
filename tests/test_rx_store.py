from il2p.runtime import LinkState, RxStore


def test_rx_result_ids_are_monotonic_and_pollable():
    store = RxStore()
    store.append_result(valid=False, reason="HEADER_RS decode failed")
    store.append_result(valid=True, src="HA2ZB-0", dst="APIL2P-0", aprs_text="test")
    assert store.last_result_id == 2
    items = store.list_results(since=1)
    assert len(items) == 1
    assert items[0]["id"] == 2
    assert items[0]["valid"] is True


def test_tx_states_pause_rx():
    store = RxStore()
    store.set_state(LinkState.TX_ACTIVE, "local transmit")
    assert store.tx_active is True
    assert store.rx_active is False
    store.set_state(LinkState.IDLE)
    assert store.tx_active is False
    assert store.rx_active is True
