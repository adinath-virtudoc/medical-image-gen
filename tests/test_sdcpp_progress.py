from pathlib import Path

import pytest

from medimg.sdcpp.progress import ParseState, ProgressParser, classify_failure, split_lines

FIX = Path(__file__).parent / "fixtures" / "sdcpp"


def text(name: str) -> str:
    return (FIX / name).read_bytes().decode("utf-8", errors="replace")


def run(name: str, size: int | None = None):
    t = text(name)
    p = ProgressParser()
    ev = []
    if size is None:
        size = len(t) or 1
    for i in range(0, len(t), size):
        ev += p.feed(t[i:i + size])
    return p, ev


EXPECTED = [("denoising", k, 8) for k in range(1, 9)] + [("decoding", 8, 8)]


@pytest.mark.parametrize("size", [1, 7, 4096])
def test_cpu_success(size):
    p, ev = run("cpu_success_512_8steps.log", size)
    assert ev == EXPECTED
    s = p.state
    assert isinstance(s, ParseState)
    assert s.sample_s == 269.75 and s.decode_s == 69.28
    assert s.encode_s == 3.24
    assert s.total_s == 342.29
    assert s.saved_ok is True and s.saved_path == "test_cpu.png"
    assert s.phase == "done" and s.failure_class is None
    assert len(s.tail) <= 60


@pytest.mark.parametrize("name", ["vulkan_oom_text_encoder.log", "vulkan_oom_diffusion_te_cpu.log"])
def test_vulkan_oom(name):
    p, ev = run(name, 100)
    assert ev == []
    assert p.state.failure_class == "gpu_oom"
    cls, cause, fix = classify_failure(1, p.state)
    assert cls == "gpu_oom"
    assert cause == "The graphics chip ran out of memory."
    assert fix == "Using the processor instead; this is slower but works."


def test_missing_model():
    p, _ = run("missing_model.log")
    assert p.state.failure_class == "no_model"
    assert classify_failure(1, p.state) == (
        "no_model", "A model file is missing or damaged.",
        "Run setup again; it re-downloads only what is missing.")


@pytest.mark.parametrize("rc", [-9, 0xC0000017, -1073741801, 0xC000012D])
def test_crash_is_ram_oom(rc):
    cls, cause, fix = classify_failure(rc, ProgressParser().state)
    assert cls == "ram_oom"
    assert cause == "The computer ran out of memory while making the image."
    assert "512x512" in fix


@pytest.mark.parametrize("rc", [0xC00000FD, -1073741571])
def test_stack_overflow_is_crash_not_oom(rc):
    cls, cause, fix = classify_failure(rc, ProgressParser().state)
    assert cls == "unknown"
    assert "0xC00000FD" in cause and "stack overflow" in cause


def test_known_crash_names():
    cause = classify_failure(0xC0000005, ProgressParser().state)[1]
    assert "access violation" in cause


@pytest.mark.parametrize("rc", [0xC0000005, -1073741819, 0xC0000135, 0xC000001D])
def test_other_nt_crash_is_not_ram_oom(rc):
    cls, cause, fix = classify_failure(rc, ProgressParser().state)
    assert cls == "unknown"
    assert "crashed" in cause and "0xC0000" in cause


def test_ram_oom_marker():
    p = ProgressParser()
    p.feed("[E] std::bad_alloc --- x.cpp:1\n")
    assert classify_failure(1, p.state)[0] == "ram_oom"


def test_gpu_oom_beats_ram_oom():
    p = ProgressParser()
    p.feed("std::bad_alloc\nErrorOutOfDeviceMemory\n")
    assert p.state.failure_class == "gpu_oom"


def test_unknown_with_error_line():
    p = ProgressParser()
    p.feed("[E] generate failed --- main.cpp:926\n")
    cls, cause, fix = classify_failure(1, p.state)
    assert cls == "unknown"
    assert cause == "The image program stopped with code 1. generate failed"
    assert fix.startswith("Try again; if it repeats, run `assess --json`")


def test_unknown_without_error_line():
    cls, cause, _ = classify_failure(1, ProgressParser().state)
    assert (cls, cause) == ("unknown", "The image program stopped with code 1.")


def test_split_lines_strips_el():
    assert split_lines("a\x1b[K\r  b  \r\n\r\nc") == ["a", "  b", "c"]
    assert split_lines("  |==| 1/8 - 3.00s/it�[K") == ["  |==| 1/8 - 3.00s/it"]


def test_cr_split_across_feeds():
    p = ProgressParser()
    assert p.feed("[I] generating image: 1/1 - seed 42\n") == []
    assert p.feed("  |=====>   | 1/8 -  34.12s/it - ETA 03:58\x1b[K") == [("denoising", 1, 8)]
    assert p.feed("\r") == []
    assert p.feed("  |=====>   | 1/8 -  34.12s/it - ETA 03:58\r") == []  # duplicate k


def test_bars_outside_denoising_ignored():
    p = ProgressParser()
    assert p.feed("  |=====>   | 1/9 -   8.52s/it - ETA 01:08\r\n") == []


def test_tail_capped():
    p = ProgressParser()
    p.feed("".join(f"line {i}\n" for i in range(200)))
    assert len(p.state.tail) == 60 and p.state.tail[-1] == "line 199"


def test_bar_reported_without_waiting_for_next_cr():
    from medimg.sdcpp.progress import ProgressParser
    p = ProgressParser()
    p.feed("[I] generating image: 1/1 - seed 42\n")
    got = []
    for k in range(1, 9):
        got += p.feed(f"\r  |====>   | {k}/8 -   6.25s/it - ETA 00:10\x1b[K")
        assert got[-1] == ("denoising", k, 8)
    assert len(got) == 8
