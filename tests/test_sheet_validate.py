from openpyxl import Workbook

from medimg.sheet import build_report, read_rows, validate

H = ["Subject", "Unit", "Lecture", "Image Prompt", "Image Name", "Status", "Size", "Seed"]
ADULT = "a 45-year-old adult woman at a desk"
MINOR = "a teen boy at a desk"


def make(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(H)
    for r in rows:
        ws.append(r)
    wb.save(path)


def mixed(path):
    make(path, [
        ["S", "U", "L", ADULT, "done_one", "done", None, None],        # 2 done
        ["S", "U", "L", ADULT, "pending_one", None, None, None],       # 3 pending
        ["S", "U", "L", MINOR, "minor_one", "pending", None, None],    # 4 blocked
        ["S", "U", "L", None, "no_prompt", None, None, None],          # 5 invalid
        ["S", "U", "L", ADULT, "Same", None, None, None],              # 6 invalid
        ["S", "U", "L", ADULT, "same", None, None, None],              # 7 invalid (case-insensitive)
        ["S", "U", "L", ADULT, "bad_size", None, "huge", None],        # 8 invalid
    ])


def test_mixed_sheet_counts_and_reasons(tmp_path):
    p = tmp_path / "m.xlsx"
    mixed(p)
    rep = build_report(p, "m.xlsx", output_root=tmp_path / "out", default_size=(1024, 1024),
                       retry_failed=False)
    assert rep.counts == {"total": 7, "done": 1, "pending": 1, "blocked": 1, "failed": 0, "invalid": 4}
    by = {r.idx: r for r in rep.rows}
    assert by[2].status == "done" and by[3].status == "pending"
    assert by[4].status == "blocked" and by[4].error.startswith("Blocked: ")
    assert by[5].status == "invalid" and "Missing Image Prompt" in by[5].error
    assert by[6].status == "invalid" and "Same output path as row 7" in by[6].error
    assert by[7].status == "invalid" and "Same output path as row 6" in by[7].error
    assert by[8].status == "invalid" and "768x1344" in by[8].error
    assert by[3].size == (1024, 1024)
    assert {p.row for p in rep.problems} == {4, 5, 6, 7, 8}
    assert all(p.reason and p.fix for p in rep.problems)
    assert rep.filters == {"subjects": ["S"], "units": ["U"], "lectures": ["L"]}
    assert rep.worksheet == "Sheet" and rep.original_name == "m.xlsx"


def kw(root, retry=False):
    return dict(output_root=root, default_size=(1024, 1024), retry_failed=retry)


def test_file_exists_marks_done(tmp_path):
    p = tmp_path / "m.xlsx"
    make(p, [["S", "U", "L", ADULT, "img", None, None, None]])
    _, rows = read_rows(p)
    out = tmp_path / "out"
    assert validate(rows, **kw(out))[0].status == "pending"
    target = out / rows[0].rel_path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"png")
    r = validate(rows, **kw(out))[0]
    assert r.status == "done" and r.system["Output Path"] == rows[0].rel_path and r.error == ""


def test_done_row_with_minor_term_stays_done(tmp_path):
    p = tmp_path / "m.xlsx"
    make(p, [["S", "U", "L", MINOR, "img", "done", None, None]])
    _, rows = read_rows(p)
    assert validate(rows, **kw(tmp_path))[0].status == "done"


def test_failed_kept_unless_retry(tmp_path):
    p = tmp_path / "m.xlsx"
    make(p, [["S", "U", "L", ADULT, "img", "failed", None, None]])
    _, rows = read_rows(p)
    assert validate(rows, **kw(tmp_path))[0].status == "failed"
    assert validate(rows, **kw(tmp_path, retry=True))[0].status == "pending"


def test_blocked_and_invalid_recomputed(tmp_path):
    p = tmp_path / "m.xlsx"
    make(p, [["S", "U", "L", ADULT, "a", "blocked", None, None],
             ["S", "U", "L", ADULT, "b", "invalid", None, None]])
    _, rows = read_rows(p)
    assert [r.status for r in validate(rows, **kw(tmp_path))] == ["pending", "pending"]


def test_input_rows_not_mutated(tmp_path):
    p = tmp_path / "m.xlsx"
    make(p, [["S", "U", "L", MINOR, "a", None, None, None]])
    _, rows = read_rows(p)
    validate(rows, **kw(tmp_path))
    assert rows[0].status == "pending"


def test_seed_out_of_range_is_invalid(tmp_path):
    p = tmp_path / "s.xlsx"
    make(p, [
        ["S", "U", "L", ADULT, "big", None, None, 99999999999],
        ["S", "U", "L", ADULT, "max", None, None, 2147483647],
    ])
    rep = build_report(p, "s.xlsx", output_root=tmp_path / "out", default_size=(1024, 1024),
                       retry_failed=False)
    by = {r.idx: r for r in rep.rows}
    assert by[2].status == "invalid"
    assert by[2].error == "Seed must be 0-2147483647. Fix: change or clear the Seed cell."
    assert by[3].status == "pending"
