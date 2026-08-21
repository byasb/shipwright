from shipwright.pipeline import _verdict


def test_operator_items_never_block_but_unfixed_blocks_do():
    assert _verdict([{"severity": "WARN", "operator": True}]) == "PASS"
    assert _verdict([{"severity": "BLOCK", "operator": False}]) == "BLOCKED"
    assert _verdict([{"severity": "BLOCK", "operator": True}, {"severity": "INFO"}]) == "PASS"
