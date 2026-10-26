from medimg.sheet import Row, select_batch


def row(idx, status="pending", subject="A", unit="U1", lecture="L1"):
    return Row(idx=idx, subject=subject, unit=unit, lecture=lecture, prompt="p", image_name=f"n{idx}",
               status=status, size=None, seed=None, error="", rel_path=f"x/{idx}.png", system={})


ROWS = [row(2), row(3, "blocked"), row(4, "invalid"), row(5, "done"), row(6, subject="B"),
        row(7, "failed"), row(8), row(9, subject="B", unit="U2"), row(10)]


def ids(rs):
    return [r.idx for r in rs]


def test_first_n_pending_in_order_skipping_others():
    assert ids(select_batch(ROWS, 3, None)) == [2, 6, 8]
    assert ids(select_batch(ROWS, 100, None)) == [2, 6, 8, 9, 10]
    assert select_batch(ROWS, 0, None) == []


def test_filter():
    assert ids(select_batch(ROWS, 10, {"subject": "b"})) == [6, 9]
    assert ids(select_batch(ROWS, 10, {"subject": "B", "unit": "U2"})) == [9]
    assert ids(select_batch(ROWS, 1, {"subject": "A"})) == [2]
    assert ids(select_batch(ROWS, 10, {"subject": "", "lecture": ""})) == [2, 6, 8, 9, 10]
    assert select_batch(ROWS, 5, {"subject": "Nope"}) == []
